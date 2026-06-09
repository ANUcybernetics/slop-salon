/**
 * Fullscreen, zero-chrome media viewer for the feed.
 *
 * One delegated click handler per feed root opens a single shared <dialog>
 * (showModal -> top layer, focus trap, Esc-to-close) wrapping a horizontal
 * CSS scroll-snap track. The browser owns the swipe momentum, so the gesture
 * is native-smooth with no JS in the hot path. Slides are windowed: only the
 * active image +/- 1 carry a real <img src>.
 *
 * The gallery spans every piece of media currently shown in the feed (in DOM
 * order), snapshotted to plain objects at open time so a feed refresh can't
 * invalidate it mid-view. Video slides play HLS — natively on Safari/iOS, via
 * a dynamically-imported hls.js elsewhere — only while they are the active slide.
 */

import type Hls from "hls.js";

export type GalleryItem = {
  kind: "image" | "video";
  /** Small source (image thumb / video poster) — currently used as the video poster. */
  src: string;
  /** Large source shown in the viewer (image fullsize, or video poster). */
  full: string;
  alt: string;
  /** HLS playlist URL, video only. */
  playlist?: string;
};

type AnchorData = {
  kind: "image" | "video";
  href: string;
  imgSrc: string;
  alt: string;
  playlist?: string;
};

/** Map a feed anchor's data to a gallery item. Pure, so it is unit-tested. */
export function toGalleryItem(a: AnchorData): GalleryItem {
  return {
    kind: a.kind,
    src: a.imgSrc,
    full: a.kind === "video" ? a.imgSrc : a.href,
    alt: a.alt,
    playlist: a.playlist,
  };
}

function readGalleryItem(a: HTMLAnchorElement): GalleryItem {
  const img = a.querySelector("img");
  return toGalleryItem({
    kind: a.dataset.kind === "video" ? "video" : "image",
    href: a.getAttribute("href") ?? "",
    imgSrc: img?.getAttribute("src") ?? "",
    alt: img?.getAttribute("alt") ?? "",
    playlist: a.dataset.playlist,
  });
}

const TAP_MOVE_PX = 10;
const TAP_MS = 350;
// Slides either side of the active one to preload (build the <img> / video poster).
const PRELOAD = 3;

const CSS = `
.ss-lb {
  position: fixed;
  inset: 0;
  width: 100dvw;
  height: 100dvh;
  max-width: 100dvw;
  max-height: 100dvh;
  margin: 0;
  padding: 0;
  border: 0;
  background: #000;
  overflow: hidden;
}
.ss-lb::backdrop { background: #000; }
.ss-lb-track {
  display: flex;
  width: 100%;
  height: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  scroll-snap-type: x mandatory;
  overscroll-behavior: contain;
  scrollbar-width: none;
}
.ss-lb-track::-webkit-scrollbar { display: none; }
.ss-lb-slide {
  flex: 0 0 100%;
  width: 100%;
  height: 100%;
  scroll-snap-align: center;
  scroll-snap-stop: always;
  display: grid;
  place-items: center;
  overflow: hidden;
}
.ss-lb-media {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: auto;
  object-fit: contain;
  display: block;
}
.ss-lb-btn {
  position: fixed;
  border: 0;
  background: transparent;
  color: #fff;
  cursor: pointer;
  text-shadow: 0 1px 3px rgb(0 0 0 / 60%);
  -webkit-tap-highlight-color: transparent;
}
.ss-lb-btn:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.ss-lb-close {
  top: max(0.5rem, env(safe-area-inset-top));
  right: max(0.5rem, env(safe-area-inset-right));
  width: 2.75rem;
  height: 2.75rem;
  font-size: 1.75rem;
  line-height: 1;
  opacity: 0.6;
  border-radius: 50%;
}
.ss-lb-close:hover { opacity: 1; }
.ss-lb-nav {
  top: 50%;
  transform: translateY(-50%);
  width: 3.5rem;
  height: 3.5rem;
  font-size: 2.75rem;
  line-height: 1;
  display: none;
  place-items: center;
  opacity: 0.55;
}
.ss-lb-nav:hover { opacity: 1; }
.ss-lb-prev { left: 0.5rem; }
.ss-lb-next { right: 0.5rem; }
@media (hover: hover) and (pointer: fine) {
  .ss-lb-nav { display: grid; }
}
.ss-lb-status {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  border: 0;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
`;

type UI = {
  dialog: HTMLDialogElement;
  track: HTMLElement;
  status: HTMLElement;
};

const boundRoots = new WeakSet<HTMLElement>();
let ui: UI | null = null;

// Per-open state.
let items: GalleryItem[] = [];
let currentIndex = 0;
let invoker: HTMLElement | null = null;
let scrollSettleTimer: ReturnType<typeof setTimeout> | undefined;
// hls.js instances keyed by slide index (native-HLS videos aren't tracked here).
const players = new Map<number, Hls>();
let playingVideo: HTMLVideoElement | null = null;

function prefersReducedMotion(): boolean {
  return matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function button(cls: string, label: string, glyph: string): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = cls;
  b.setAttribute("aria-label", label);
  b.textContent = glyph;
  return b;
}

function ensureUI(): UI {
  if (ui) return ui;

  const style = document.createElement("style");
  style.id = "ss-lb-style";
  style.textContent = CSS;
  document.head.appendChild(style);

  const dialog = document.createElement("dialog");
  dialog.className = "ss-lb";
  dialog.setAttribute("aria-label", "Media viewer");
  dialog.setAttribute("closedby", "any");

  const track = document.createElement("div");
  track.className = "ss-lb-track";

  const status = document.createElement("div");
  status.className = "ss-lb-status";
  status.setAttribute("aria-live", "polite");

  const closeBtn = button("ss-lb-btn ss-lb-close", "Close", "×");
  const prevBtn = button("ss-lb-btn ss-lb-nav ss-lb-prev", "Previous", "‹");
  const nextBtn = button("ss-lb-btn ss-lb-nav ss-lb-next", "Next", "›");

  dialog.append(track, closeBtn, prevBtn, nextBtn, status);
  document.body.appendChild(dialog);

  ui = { dialog, track, status };

  closeBtn.addEventListener("click", () => dialog.close());
  prevBtn.addEventListener("click", () => go(currentIndex - 1));
  nextBtn.addEventListener("click", () => go(currentIndex + 1));

  dialog.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      go(currentIndex + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      go(currentIndex - 1);
    }
  });

  // Catch swipes: when the snap scroll settles on a new slide, make it active.
  track.addEventListener("scroll", () => {
    if (scrollSettleTimer) clearTimeout(scrollSettleTimer);
    scrollSettleTimer = setTimeout(() => {
      if (!ui || items.length === 0) return;
      const i = Math.round(ui.track.scrollLeft / ui.track.clientWidth);
      if (i !== currentIndex) setActive(i);
    }, 120);
  });

  // Tap-to-close: a quick, low-movement press that isn't a swipe and isn't on a
  // video (whose controls own the tap) dismisses the viewer.
  let downX = 0;
  let downY = 0;
  let downT = 0;
  track.addEventListener("pointerdown", (e) => {
    downX = e.clientX;
    downY = e.clientY;
    downT = e.timeStamp;
  });
  track.addEventListener("pointerup", (e) => {
    const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
    const onVideo = (e.target as Element).closest("video");
    if (moved < TAP_MOVE_PX && e.timeStamp - downT < TAP_MS && !onVideo) {
      dialog.close();
    }
  });

  dialog.addEventListener("close", onClose);

  return ui;
}

function lockScroll(): void {
  document.documentElement.style.overflow = "hidden";
}

function unlockScroll(): void {
  document.documentElement.style.overflow = "";
}

function updateStatus(): void {
  if (ui) ui.status.textContent = `${currentIndex + 1} of ${items.length}`;
}

function hydrate(i: number): void {
  if (!ui || i < 0 || i >= items.length) return;
  const slide = ui.track.children[i] as HTMLElement;
  if (slide.dataset.hydrated === "1") return;
  slide.dataset.hydrated = "1";
  const item = items[i];
  if (item.kind === "video") {
    // The poster only; the HLS source is attached when the slide goes active.
    const video = document.createElement("video");
    video.className = "ss-lb-media";
    video.controls = true;
    video.playsInline = true;
    video.muted = true;
    video.preload = "none";
    if (item.full) video.poster = item.full;
    video.setAttribute("aria-label", item.alt || "Video");
    slide.appendChild(video);
  } else {
    const img = document.createElement("img");
    img.className = "ss-lb-media";
    img.alt = item.alt;
    img.decoding = "async";
    img.src = item.full;
    slide.appendChild(img);
  }
}

function setActive(i: number): void {
  currentIndex = i;
  for (let d = -PRELOAD; d <= PRELOAD; d++) hydrate(i + d);
  updateStatus();

  // Only the active slide plays; pause whatever was playing first.
  if (playingVideo) {
    playingVideo.pause();
    playingVideo = null;
  }
  if (items[i]?.kind === "video") void playVideo(i);

  // Free hls.js pipelines that have fallen outside the ±1 window.
  for (const [j, hls] of players) {
    if (Math.abs(j - i) > 1) {
      hls.destroy();
      players.delete(j);
    }
  }
}

async function playVideo(i: number): Promise<void> {
  if (!ui) return;
  const item = items[i];
  if (!item?.playlist) return;
  const video = (ui.track.children[i] as HTMLElement | undefined)?.querySelector("video");
  if (!video) return;
  playingVideo = video;

  if (!video.src && !players.has(i)) {
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = item.playlist; // native HLS (Safari / iOS)
    } else {
      const { default: Hls } = await import("hls.js");
      // The viewer may have moved on or closed while the chunk loaded.
      if (currentIndex !== i || !video.isConnected) return;
      if (Hls.isSupported()) {
        const hls = new Hls();
        hls.loadSource(item.playlist);
        hls.attachMedia(video);
        players.set(i, hls);
      } else {
        video.src = item.playlist;
      }
    }
  }

  // Autoplay muted; a blocked play() or reduced-motion just leaves the poster up.
  if (!prefersReducedMotion()) {
    video.play().catch(() => {});
  }
}

// Navigate to a slide. currentIndex moves synchronously so rapid arrow presses
// accumulate (each computes from the updated index, not a lagging observer).
function go(i: number): void {
  if (!ui) return;
  const clamped = Math.max(0, Math.min(items.length - 1, i));
  setActive(clamped);
  ui.track.scrollTo({
    left: clamped * ui.track.clientWidth,
    behavior: prefersReducedMotion() ? "auto" : "smooth",
  });
}

function open(list: GalleryItem[], start: number, from: HTMLElement | null): void {
  const { dialog, track } = ensureUI();
  items = list;
  currentIndex = start;
  invoker = from;

  track.replaceChildren();
  for (let i = 0; i < items.length; i++) {
    const slide = document.createElement("div");
    slide.className = "ss-lb-slide";
    slide.dataset.index = String(i);
    track.appendChild(slide);
  }

  lockScroll();
  if (!dialog.open) dialog.showModal();

  // Jump (not animate) to the clicked slide once the dialog has laid out, so
  // clientWidth is final before we compute the offset.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      track.scrollLeft = start * track.clientWidth;
      setActive(start);
    });
  });
}

function onClose(): void {
  unlockScroll();
  for (const hls of players.values()) hls.destroy();
  players.clear();
  playingVideo = null;
  ui?.track.replaceChildren();
  items = [];
  const back = invoker && invoker.isConnected ? invoker : null;
  invoker = null;
  back?.focus();
}

/**
 * Wire a feed container so clicking any media opens the viewer. Idempotent and
 * delegated, so it survives the feed re-rendering its children.
 */
export function attachLightbox(root: HTMLElement | null): void {
  if (!root || boundRoots.has(root)) return;
  boundRoots.add(root);
  root.addEventListener("click", (e) => {
    const anchor = (e.target as Element).closest<HTMLAnchorElement>(".post-images a");
    if (!anchor || !root.contains(anchor)) return;
    // Let modified / non-primary clicks keep their default (open in a new tab).
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const anchors = Array.from(root.querySelectorAll<HTMLAnchorElement>(".post-images a"));
    const index = anchors.indexOf(anchor);
    if (index < 0) return;
    e.preventDefault();
    open(anchors.map(readGalleryItem), index, anchor);
  });
}
