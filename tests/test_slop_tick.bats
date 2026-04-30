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
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
# Stub: writes a tick artifact when given any prompt
echo "tick-output" > "$PWD/tick-$$.txt"
EOF
    chmod +x "$STUB_DIR/claude"

    # Wrap git so `push` is a no-op (no remote in test)
    REAL_GIT="$(command -v git)"
    cat > "$STUB_DIR/git" <<EOF
#!/usr/bin/env bash
if [[ "\$1" == "push" ]]; then
    exit 0
fi
exec "$REAL_GIT" "\$@"
EOF
    chmod +x "$STUB_DIR/git"

    export PATH="$STUB_DIR:$PATH"
    export HOME="$TEST_HOME"
    export AGENT_NAME

    SCRIPT="$BATS_TEST_DIRNAME/../templates/slop-tick"
}

teardown() {
    rm -rf "$TEST_HOME" "$STUB_DIR"
}

@test "fails without AGENT_NAME" {
    unset AGENT_NAME
    run bash "$SCRIPT" "tick"
    [ "$status" -ne 0 ]
    [[ "$output" == *"AGENT_NAME"* ]]
}

@test "fails without prompt argument" {
    run bash "$SCRIPT"
    [ "$status" -ne 0 ]
    [[ "$output" == *"usage"* ]]
}

@test "runs claude and creates a commit when files change" {
    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]
    cd "$AGENT_DIR"
    log_count=$(git log --oneline | wc -l)
    [ "$log_count" -ge 2 ]
}

@test "skips commit when nothing changed" {
    cat > "$STUB_DIR/claude" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$STUB_DIR/claude"

    cd "$AGENT_DIR"
    initial_count=$(git log --oneline | wc -l)

    run bash "$SCRIPT" "tick"
    [ "$status" -eq 0 ]

    cd "$AGENT_DIR"
    new_count=$(git log --oneline | wc -l)
    [ "$initial_count" -eq "$new_count" ]
}
