#!/usr/bin/env bats

setup() {
    TEST_HOME="$(mktemp -d)"
    AGENT_NAME="testagent"
    AGENT_DIR="$TEST_HOME/slop-salon-$AGENT_NAME"
    mkdir -p "$AGENT_DIR"
    cd "$AGENT_DIR"
    git init -q -b main
    git config user.email "t@example.com"
    git config user.name "Test"
    git config commit.gpgsign false
    echo "initial" > seed.txt
    git add seed.txt
    git commit -q -m "seed"

    STUB_DIR="$(mktemp -d)"
    # Stub agent-run: record argv and what the agent could see, then write a
    # tick artifact so a commit happens.
    cat > "$STUB_DIR/agent-run" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$HOME/agent-argv.txt"
cat "$HOME/.codex/auth.json" > "$HOME/auth-seen.txt" 2>/dev/null || true
echo "${SLOP_CODEX_AUTH:-unset}" > "$HOME/auth-env-seen.txt"
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/agent-run"

    cat > "$STUB_DIR/slop-prompt" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$HOME/slop-prompt-argv.txt"
EOF
    chmod +x "$STUB_DIR/slop-prompt"

    # Wrap git so push/pull are no-ops (no remote in test).
    REAL_GIT="$(command -v git)"
    cat > "$STUB_DIR/git" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "push" || "\$1" == "pull" ]]; then
    echo "git \$1" >> "\$HOME/git-calls.txt"
    exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
    chmod +x "$STUB_DIR/git"

    # pkill would otherwise match (and kill) the host's own shells.
    printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB_DIR/pkill"
    chmod +x "$STUB_DIR/pkill"

    export HOME="$TEST_HOME"
    export AGENT_NAME
    export AGENT_PROFILE="claude-sub"
    unset SLOP_RUNNER SLOP_CODEX_AUTH CLAUDE_CODE_SHELL_PREFIX
    export PATH="$STUB_DIR:$PATH"
    SLOP_TICK="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/templates/slop-tick"
}

teardown() {
    rm -rf "$TEST_HOME" "$STUB_DIR"
}

codex_tick() {
    export SLOP_RUNNER=codex AGENT_PROFILE=codex-sub
    export SLOP_CODEX_AUTH="$(printf '{"auth_mode":"chatgpt"}' | base64 -w0)"
}

@test "fails without AGENT_NAME" {
    unset AGENT_NAME
    run "$SLOP_TICK" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"AGENT_NAME"* ]]
}

@test "fails without a prompt" {
    run "$SLOP_TICK"
    [ "$status" -ne 0 ]
    [[ "$output" == *"usage"* ]]
}

@test "fails without AGENT_PROFILE" {
    unset AGENT_PROFILE
    run "$SLOP_TICK" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"AGENT_PROFILE"* ]]
}

@test "runs agent-run with the profile, the denied tools and the prompt, then commits and pushes" {
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    argv="$(cat "$HOME/agent-argv.txt")"
    [[ "$argv" == *"--profile"$'\n'"claude-sub"* ]]
    [[ "$argv" == *"--bypass-permissions"* ]]
    [[ "$argv" == *"--claude-disallowed-tools"$'\n'"AskUserQuestion"* ]]
    [ "$(tail -1 "$HOME/agent-argv.txt")" = "tick" ]
    git log --oneline | grep -q "session"
    grep -q "git pull" "$HOME/git-calls.txt"
    grep -q "git push" "$HOME/git-calls.txt"
}

@test "SLOP_DENIED_TOOLS overrides the denied-tool list" {
    export SLOP_DENIED_TOOLS="AskUserQuestion,WebSearch"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    grep -q "AskUserQuestion,WebSearch" "$HOME/agent-argv.txt"
}

@test "a codex tick renders AGENTS.md and holds the login only for the tick" {
    codex_tick
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    grep -q "agents-md" "$HOME/slop-prompt-argv.txt"
    [ "$(cat "$HOME/auth-seen.txt")" = '{"auth_mode":"chatgpt"}' ]
    [ "$(cat "$HOME/auth-env-seen.txt")" = "unset" ]
    [ ! -e "$HOME/.codex/auth.json" ]
    ! grep -q -- "--claude-disallowed-tools" "$HOME/agent-argv.txt"
    [ "$(tail -1 "$HOME/agent-argv.txt")" = "tick" ]
}

@test "a codex tick runs under the memory cap when one is given" {
    codex_tick
    cat > "$STUB_DIR/toolcap" <<'EOF'
#!/bin/bash
echo capped > "$HOME/capped.txt"
exec bash -c "$1"
EOF
    chmod +x "$STUB_DIR/toolcap"
    export CLAUDE_CODE_SHELL_PREFIX="$STUB_DIR/toolcap"
    run "$SLOP_TICK" "a prompt with 'quotes' and spaces"
    [ "$status" -eq 0 ]
    [ -f "$HOME/capped.txt" ]
    [ "$(tail -1 "$HOME/agent-argv.txt")" = "a prompt with 'quotes' and spaces" ]
}

@test "a codex tick without its login fails before the agent runs" {
    codex_tick
    unset SLOP_CODEX_AUTH
    run "$SLOP_TICK" "tick"
    [ "$status" -ne 0 ]
    [ ! -f "$HOME/agent-argv.txt" ]
}

@test "the agent runs with stdin closed, so codex never waits on it" {
    printf '#!/usr/bin/env bash\nif read -r -t 2 line; then echo "read: $line" > "$HOME/stdin.txt"; else echo eof > "$HOME/stdin.txt"; fi\n' > "$STUB_DIR/agent-run"
    run "$SLOP_TICK" "tick" < <(echo leaked; sleep 5)
    [ "$status" -eq 0 ]
    [ "$(cat "$HOME/stdin.txt")" = "eof" ]
}

@test "an unknown runner fails" {
    export SLOP_RUNNER=gemini
    run "$SLOP_TICK" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"unknown SLOP_RUNNER"* ]]
}

@test "commits pre-tick leftovers before pulling" {
    echo "orphan" > "$AGENT_DIR/notes-leftover.txt"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    git log --format=%s | grep -q "pre-tick leftovers"
    [ "$(git log --oneline | wc -l)" -eq 3 ]
}

@test "skips the commit when nothing changed" {
    printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB_DIR/agent-run"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    [ "$(git log --oneline | wc -l)" -eq 1 ]
    ! grep -q "git push" "$HOME/git-calls.txt" 2>/dev/null
}

@test "a failed agent still commits partial work and says so on stderr" {
    cat > "$STUB_DIR/agent-run" <<'EOF'
#!/usr/bin/env bash
echo "partial" > "$PWD/partial.txt"
exit 1
EOF
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    [[ "$output" == *"slop-tick: claude exited 1"* ]]
    git log --oneline | grep -q "session"
}

@test "reads nothing from disk but the repo: no env file is sourced" {
    printf 'export AGENT_NAME=someone-else\n' > "$HOME/.slop-env"
    run "$SLOP_TICK" "tick"
    [ "$status" -eq 0 ]
    [ -f "$AGENT_DIR/tick-"*.txt ]
}
