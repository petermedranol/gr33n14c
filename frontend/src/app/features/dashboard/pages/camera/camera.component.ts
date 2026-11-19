import {
  AfterViewInit,
  Component,
  ElementRef,
  HostListener,
  OnDestroy,
  OnInit,
  TemplateRef,
  ViewChild,
  signal,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';
import { HttpClient } from '@angular/common/http';
import Hls from 'hls.js';
import { environment } from '../../../../../environments/environment';
import { HeaderService } from '../../../../core/services/header.service';
import { UserSettingsService } from '../../../../core/services/user-settings.service';

// ─── API shapes ─────────────────────────────────────────────────────────────

interface CctvCamera {
  id: string;
  name: string;
}

interface Recording {
  name: string;
  date: string;
  start: string;      // ISO datetime  e.g. "2026-11-17T09:43:00"
  size: number;       // bytes
  backed_up: boolean; // already uploaded to Cloudflare R2
  web_ready: boolean; // PC has converted a browser-playable H.264 copy
}

interface DetectionEvent {
  camera: string;
  ts: string;
  count: number;
  file: string;
  start: string;       // ISO datetime
  web_ready?: boolean; // the segment holding it has a browser-playable copy
}

interface BarkEvent {
  camera: string;      // which camera logged it (garage / patiopapas)
  ts: string;
  score: number;       // 0..1 bark intensity from PANNs
  person: number;      // 1 if a person was on camera (fusion)
  file: string;        // wav clip name
  img: string;         // snapshot name ('' if none)
  start: string;       // ISO datetime
}

// ─── Camera selector type ────────────────────────────────────────────────────

type CameraId = 'greenhouse' | 'garage' | 'patiopapas' | '321' | 'eventos' | 'ladridos';

// IP cameras share the same UI (recordings + detection events + live).
// PTZ and bark detection are Garage-only.
const IP_CAMERAS: CameraId[] = ['garage', 'patiopapas', '321'];
// Cameras with a working live feed. 321 (Nevería) is a cloud cam whose stream only
// passes through (can't be decoded for live), so it's recordings-only.
const LIVE_CAMERAS: CameraId[] = ['garage', 'patiopapas'];

interface CameraTab {
  id: CameraId;
  label: string;
  icon: string;
}

@Component({
  selector: 'app-camera',
  standalone: true,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './camera.component.html',
  styleUrl: './camera.component.scss',
})
export class CameraComponent implements OnInit, AfterViewInit, OnDestroy {
  private http = inject(HttpClient);
  private header = inject(HeaderService);
  private settings = inject(UserSettingsService);
  private api = environment.apiUrl;

  // Tabs are rendered into the shell top bar via this template.
  @ViewChild('headerActions') headerActionsTpl!: TemplateRef<unknown>;

  // ─── Camera tabs ──────────────────────────────────────────────────────────
  tabs: CameraTab[] = [
    { id: 'greenhouse', label: 'Invernadero', icon: 'leaf' },
    { id: 'garage',     label: 'Garage',      icon: 'warehouse' },
    { id: 'patiopapas', label: 'Patio Papás', icon: 'house' },
    { id: '321',        label: 'Nevería',     icon: 'cloud' },
    { id: 'eventos',    label: 'Eventos',     icon: 'images' },
    { id: 'ladridos',   label: 'Ladridos',    icon: 'audio-lines' },
  ];

  activeCamera = signal<CameraId>('greenhouse');

  // ─── Live feed ────────────────────────────────────────────────────────────
  // Greenhouse (CSI) is a fast local JPEG refresh; Garage (IP) is an HLS stream
  // produced by the PC (GPU/NVENC) and proxied by the backend — smooth 720p that
  // survives hiccups and passes cleanly through Cloudflare.
  imgSrc         = signal<string>(`${this.api}/api/camera/photo`);
  garageLoading  = signal<boolean>(true);  // spinner until the live video starts
  imgError       = signal<string | null>(null);

  private intervalId: ReturnType<typeof setInterval> | null = null;

  // Garage live <video> element (conditionally rendered) + its hls.js player.
  private hls: Hls | null = null;
  @ViewChild('garageVideo') set garageVideo(ref: ElementRef<HTMLVideoElement> | undefined) {
    if (ref && this.hasLive(this.activeCamera()) && !this.selectedRecording()) {
      this.attachHls(ref.nativeElement);
    } else {
      this.detachHls();
    }
  }

  /** Is this an IP camera (garage/patiopapas/321) — i.e. the recordings+events UI? */
  isIpCam(id: string): boolean {
    return (IP_CAMERAS as string[]).includes(id);
  }

  /** Does this camera have a working live feed? (321/Nevería is recordings-only.) */
  hasLive(id: string): boolean {
    return (LIVE_CAMERAS as string[]).includes(id);
  }

  // ─── Recordings panel (Garage only) ───────────────────────────────────────
  availableDays    = signal<string[]>([]);
  selectedDay      = signal<string>('');
  recordings       = signal<Recording[]>([]);
  selectedRecording = signal<Recording | null>(null);
  videoError       = signal<boolean>(false);
  recordingsError  = signal<string | null>(null);
  daysError        = signal<string | null>(null);

  // ─── Events gallery ────────────────────────────────────────────────────────
  events      = signal<DetectionEvent[]>([]);
  eventsError = signal<string | null>(null);
  // Map of recording filename → detection events that fall inside its 10-min window.
  private recEventsMap = signal<Record<string, DetectionEvent[]>>({});

  // Lightbox (full-screen image preview).
  lightboxImg = signal<string | null>(null);

  // ─── Lifecycle ────────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.header.set({
      title: 'Cámaras en vivo',
      subtitle: 'Monitoreo en tiempo real · Invernadero y Garage',
      icon: 'camera',
    });
    // Restore the last active tab so a refresh keeps you where you were.
    this.activate(this.settings.get<CameraId>('cameraTab', 'greenhouse'));
  }

  ngAfterViewInit(): void {
    // Publish the tabs into the shell top bar (deferred to avoid CD conflict).
    Promise.resolve().then(() => this.header.setActions(this.headerActionsTpl));
  }

  ngOnDestroy(): void {
    this.clearInterval();
    this.detachHls();
    this.header.clear();
  }

  // ─── Tab switching ────────────────────────────────────────────────────────

  selectCamera(id: CameraId): void {
    if (this.activeCamera() === id) return;
    this.settings.set('cameraTab', id);  // remember across refresh
    this.activate(id);
  }

  /** Switch to a tab and run its setup (shared by clicks and restore-on-load). */
  private activate(id: CameraId): void {
    this.clearInterval();
    this.detachHls();  // stop any running Garage live by default
    this.activeCamera.set(id);
    this.imgError.set(null);

    if (this.isIpCam(id)) {
      // The HLS player attaches once the <video> renders (see garageVideo setter).
      this.selectedRecording.set(null);  // don't carry a recording across cameras
      this.videoError.set(false);
      this.garageLoading.set(this.hasLive(id));  // spinner only while a live feed loads
      this.loadDays();
      this.loadEvents();          // to flag which recordings had a detection
      this.loadBarkEvents();      // bark markers on the seek bar (both IP cameras)
      if (id === 'garage') {
        this.loadPresets();       // PTZ presets + patrol status (Garage-only)
      }
    } else if (id === 'eventos') {
      this.loadEvents();
    } else if (id === 'ladridos') {
      this.loadBarkEvents();
      this.loadBarkThreshold();
    } else {
      this.startGreenhouse();
    }
  }

  // ─── Greenhouse JPEG refresh ───────────────────────────────────────────────

  private startGreenhouse(): void {
    const url = `${this.api}/api/camera/photo`;
    this.imgSrc.set(`${url}?t=${Date.now()}`);
    this.intervalId = setInterval(() => {
      this.imgSrc.set(`${url}?t=${Date.now()}`);
    }, 700);
  }

  private clearInterval(): void {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  // ─── Live feed load/error events ───────────────────────────────────────────

  onImgLoad(): void {
    this.imgError.set(null);
  }

  onImgError(): void {
    this.imgError.set('No se pudo cargar la imagen de la cámara.');
  }

  /** Spinner off once the live video starts playing. */
  onLivePlaying(): void {
    this.garageLoading.set(false);
    this.imgError.set(null);
  }

  // ─── Garage live via HLS (produced by the PC gateway) ───────────────────────

  private liveVideo: HTMLVideoElement | null = null;
  private liveWatchdog: ReturnType<typeof setInterval> | null = null;

  /** Attach an hls.js player to the live <video> and keep it glued to the live edge.
   *  A watchdog nudges playback forward if it stalls or drifts behind — otherwise a
   *  standard HLS <video> can freeze on one frame ("the seconds stop advancing"). */
  private attachHls(video: HTMLVideoElement): void {
    if (this.hls) return;  // already attached to this element
    this.liveVideo = video;
    const url = `${this.api}/api/cctv/${this.activeCamera()}/hls/stream.m3u8`;

    if (Hls.isSupported()) {
      const hls = new Hls({
        liveSyncDurationCount: 3,        // target ~3s behind the live edge
        liveMaxLatencyDurationCount: 8,  // if we fall 8s behind, jump forward
        maxLiveSyncPlaybackRate: 1.5,    // speed up slightly to catch up vs. stalling
        maxBufferLength: 30,
        backBufferLength: 10,
      });
      this.hls = hls;
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => video.play().catch(() => {}));
      hls.on(Hls.Events.FRAG_BUFFERED, () => this.onLivePlaying());
      hls.on(Hls.Events.ERROR, (_evt, data) => {
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          hls.startLoad();
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls.recoverMediaError();
        } else {
          this.detachHls();
        }
      });
      this.startLiveWatchdog();
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      // Safari / iOS play HLS natively.
      video.src = url;
      video.addEventListener('loadeddata', () => this.onLivePlaying());
      video.play().catch(() => {});
      this.startLiveWatchdog();
    } else {
      this.imgError.set('Este navegador no soporta el video en vivo (HLS).');
    }
  }

  /** Every 3s: if playback stalled or drifted behind, snap to the live edge and
   *  resume. This is what guarantees it stays truly live without a manual refresh. */
  private startLiveWatchdog(): void {
    this.stopLiveWatchdog();
    let lastTime = -1;
    this.liveWatchdog = setInterval(() => {
      const v = this.liveVideo;
      if (!v) return;
      const liveEdge = this.liveEdgePosition(v);
      // Snap forward if we've drifted too far behind the live edge.
      if (liveEdge != null && liveEdge - v.currentTime > 6) {
        try { v.currentTime = liveEdge; } catch { /* ignore */ }
      }
      // If currentTime hasn't moved since last check, it's stalled → nudge + resume.
      if (!v.paused && v.currentTime === lastTime && liveEdge != null) {
        try { v.currentTime = liveEdge; } catch { /* ignore */ }
      }
      if (v.paused) v.play().catch(() => {});
      lastTime = v.currentTime;
    }, 3000);
  }

  private stopLiveWatchdog(): void {
    if (this.liveWatchdog) {
      clearInterval(this.liveWatchdog);
      this.liveWatchdog = null;
    }
  }

  /** Position (seconds) of the live edge: hls.js's liveSyncPosition, else end of buffer. */
  private liveEdgePosition(v: HTMLVideoElement): number | null {
    const sync = this.hls?.liveSyncPosition;
    if (sync != null && isFinite(sync)) return sync;
    if (v.buffered.length > 0) return v.buffered.end(v.buffered.length - 1);
    return null;
  }

  private detachHls(): void {
    this.stopLiveWatchdog();
    if (this.hls) {
      this.hls.destroy();
      this.hls = null;
    }
    this.liveVideo = null;
  }

  // ─── PTZ control (Garage) ──────────────────────────────────────────────────
  ptzPresets      = signal<{ token: string; name: string }[]>([]);
  tourActive      = signal<boolean>(false);
  ptzError        = signal<string | null>(null);
  showPresetInput = signal<boolean>(false);
  presetName      = signal<string>('');
  // Step size (ms per arrow click) — adjustable via slider, persisted across refresh.
  ptzStepMs       = signal<number>(this.settings.get<number>('ptzStepMs', 300));

  private ptzUrl(path: string): string {
    return `${this.api}/api/cctv/garage/ptz/${path}`;
  }

  onStepSizeChange(ev: Event): void {
    const ms = Number((ev.target as HTMLInputElement).value);
    this.ptzStepMs.set(ms);
    this.settings.set('ptzStepMs', ms);
  }

  loadPresets(): void {
    this.http.get<{ presets: { token: string; name: string }[]; tour_active: boolean }>(
      this.ptzUrl('presets')
    ).subscribe({
      next: (r) => {
        this.ptzPresets.set(r.presets ?? []);
        this.tourActive.set(!!r.tour_active);
        this.ptzError.set(null);
      },
      error: () => this.ptzError.set('No se pudo contactar la cámara (PTZ).'),
    });
  }

  /** Nudge one step (one tap). Step size = slider (ms pulse). The live view lags a
   *  few seconds, so discrete steps are far easier to aim than hold-to-move. */
  ptzStep(pan: number, tilt: number, zoom: number): void {
    const duration = this.ptzStepMs() / 1000;
    this.http.post(this.ptzUrl('step'), { pan, tilt, zoom, duration }).subscribe({
      next: () => this.ptzError.set(null),
      error: () => this.ptzError.set('La cámara no aceptó el movimiento.'),
    });
  }

  gotoPreset(token: string): void {
    this.http.post(this.ptzUrl(`goto/${encodeURIComponent(token)}`), {}).subscribe({
      error: () => this.ptzError.set('No se pudo ir al preset.'),
    });
  }

  startSavePreset(): void {
    this.presetName.set('');
    this.showPresetInput.set(true);
  }

  cancelSavePreset(): void {
    this.showPresetInput.set(false);
    this.presetName.set('');
  }

  confirmSavePreset(): void {
    const name = this.presetName().trim();
    if (!name) return;
    this.http.post(this.ptzUrl('preset'), { name }).subscribe({
      next: () => {
        this.showPresetInput.set(false);
        this.presetName.set('');
        this.loadPresets();
      },
      error: () => this.ptzError.set('No se pudo guardar el preset.'),
    });
  }

  deletePreset(token: string, ev: Event): void {
    ev.stopPropagation();
    this.http.delete(this.ptzUrl(`preset/${encodeURIComponent(token)}`)).subscribe({
      next: () => this.loadPresets(),
      error: () => this.ptzError.set('No se pudo borrar el preset.'),
    });
  }

  toggleTour(): void {
    const action = this.tourActive() ? 'stop' : 'start';
    this.http.post<{ tour_active: boolean }>(this.ptzUrl('tour'), { action, dwell: 10 }).subscribe({
      next: (r) => this.tourActive.set(!!r.tour_active),
      error: () => this.ptzError.set('No se pudo cambiar la ronda.'),
    });
  }

  // ─── Recordings ──────────────────────────────────────────────────────────

  private loadDays(): void {
    this.daysError.set(null);
    this.http.get<string[]>(`${this.api}/api/cctv/${this.activeCamera()}/days`).subscribe({
      next: (days) => {
        this.availableDays.set(days);
        if (days.length > 0) {
          const savedDay = this.settings.get<string>('cameraDay', '');
          const day = days.includes(savedDay) ? savedDay : days[0];
          this.selectedDay.set(day);
          this.loadRecordings(day);
        }
      },
      error: () => {
        this.daysError.set('No se pudieron cargar las fechas de grabaciones.');
      },
    });
  }

  onDayChange(event: Event): void {
    const day = (event.target as HTMLSelectElement).value;
    this.settings.set('cameraDay', day);  // remember across refresh
    this.selectedDay.set(day);
    this.loadRecordings(day);
    this.selectedRecording.set(null);
    this.videoError.set(false);
  }

  private loadRecordings(date: string): void {
    this.recordingsError.set(null);
    this.recordings.set([]);
    this.http
      .get<Recording[]>(`${this.api}/api/cctv/${this.activeCamera()}/recordings?date=${date}`)
      .subscribe({
        next: (recs) => {
          // Sort by start time ascending
          const sorted = [...recs].sort((a, b) =>
            a.start.localeCompare(b.start)
          );
          this.recordings.set(sorted);
          this.computeRecEvents();
          // If we arrived here from an event, pick the segment that contains it
          // and queue the seek (applied when the video's metadata loads).
          const pend = this.pendingSeekStart();
          if (pend) {
            this.pendingSeekStart.set(null);
            const t = new Date(pend).getTime();
            const rec = sorted.find((r) => {
              const s = new Date(r.start).getTime();
              return t >= s && t < s + 10 * 60 * 1000;
            });
            if (rec) {
              this.pendingSeekSec = (t - new Date(rec.start).getTime()) / 1000;
              this.selectRecording(rec);
            }
          }
        },
        error: () => {
          this.recordingsError.set('No se pudieron cargar las grabaciones.');
        },
      });
  }

  selectRecording(rec: Recording): void {
    this.selectedRecording.set(rec);
    this.videoError.set(false);
  }

  closeRecording(): void {
    this.selectedRecording.set(null);
    this.videoError.set(false);
  }

  onVideoError(): void {
    this.videoError.set(true);
  }

  /** H.264 transcode for in-browser playback (Chrome). */
  playSrc(name: string): string {
    return `${this.api}/api/cctv/${this.activeCamera()}/play/${name}`;
  }

  /** Original H.265 file for download (view in VLC, full quality). */
  downloadSrc(name: string): string {
    return `${this.api}/api/cctv/${this.activeCamera()}/file/${name}`;
  }

  // ─── Reproductor de grabación (estilo YouTube) ──────────────────────────────
  @ViewChild('recVideo')      recVideo?: ElementRef<HTMLVideoElement>;
  @ViewChild('previewVideo')  previewVideo?: ElementRef<HTMLVideoElement>;
  @ViewChild('previewCanvas') previewCanvas?: ElementRef<HTMLCanvasElement>;
  @ViewChild('seekEl')        seekEl?: ElementRef<HTMLElement>;
  @ViewChild('playerEl')      playerEl?: ElementRef<HTMLElement>;

  recPlaying  = signal<boolean>(false);
  recMuted    = signal<boolean>(true);   // starts muted (autoplay policy); unmute to hear
  recCurrent  = signal<number>(0);
  recDuration = signal<number>(0);
  preview     = signal<{ show: boolean; x: number; time: number }>({ show: false, x: 0, time: 0 });
  private previewSeeking = false;
  // When jumping from a gallery: the moment (ISO) to open, and the second to seek to
  // once the segment's video has loaded.
  pendingSeekStart = signal<string | null>(null);
  private pendingSeekSec: number | null = null;

  private recEl: HTMLVideoElement | null = null;

  onRecLoaded(ev: Event): void {
    const v = ev.target as HTMLVideoElement;
    this.recEl = v;
    this.recDuration.set(v.duration || 0);
    this.recPlaying.set(!v.paused);
    // Jumped here from an event → seek to that moment once metadata is ready.
    if (this.pendingSeekSec != null) {
      const sec = this.pendingSeekSec;
      this.pendingSeekSec = null;
      try { v.currentTime = Math.max(0, sec); v.play(); } catch { /* ignore */ }
    }
  }
  /** Fires on timeupdate/play/playing/pause — read the real state straight from the
   *  element so the play/pause button never gets out of sync. */
  onRecState(ev: Event): void {
    const v = ev.target as HTMLVideoElement;
    this.recEl = v;
    this.recCurrent.set(v.currentTime || 0);
    this.recPlaying.set(!v.paused);
  }
  recProgressPct(): number {
    const d = this.recDuration();
    return d ? (this.recCurrent() / d) * 100 : 0;
  }
  togglePlay(): void {
    const v = this.recEl;
    if (!v) return;
    if (v.paused) v.play(); else v.pause();
    this.recPlaying.set(!v.paused);
  }
  seekSeconds(sec: number): void {
    const v = this.recEl;
    const d = this.recDuration();
    if (v && d) v.currentTime = Math.max(0, Math.min(d, sec));
  }
  onSeekClick(ev: MouseEvent): void {
    const bar = this.seekEl?.nativeElement;
    if (!bar) return;
    const r = bar.getBoundingClientRect();
    this.seekSeconds(((ev.clientX - r.left) / r.width) * this.recDuration());
  }
  /** Hover the seek bar → move the preview tooltip and seek the hidden video. */
  onSeekHover(ev: MouseEvent): void {
    const bar = this.seekEl?.nativeElement;
    const pv = this.previewVideo?.nativeElement;
    const d = this.recDuration();
    if (!bar || !d) return;
    const r = bar.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    this.preview.set({ show: true, x: ev.clientX - r.left, time: frac * d });
    if (pv && !this.previewSeeking) {
      this.previewSeeking = true;
      try { pv.currentTime = frac * d; } catch { this.previewSeeking = false; }
    }
  }
  onPreviewSeeked(): void {
    const pv = this.previewVideo?.nativeElement;
    const cv = this.previewCanvas?.nativeElement;
    if (pv && cv) {
      const ctx = cv.getContext('2d');
      if (ctx) { try { ctx.drawImage(pv, 0, 0, cv.width, cv.height); } catch { /* frame not ready */ } }
    }
    this.previewSeeking = false;
  }
  hidePreview(): void {
    this.preview.set({ show: false, x: 0, time: 0 });
  }
  toggleMute(): void {
    const v = this.recEl;
    if (!v) return;
    v.muted = !v.muted;
    this.recMuted.set(v.muted);
  }
  toggleFullscreen(): void {
    const el = this.playerEl?.nativeElement;
    if (!document.fullscreenElement) el?.requestFullscreen?.();
    else document.exitFullscreen?.();
  }
  /** Jump the player to a detection's moment and play. */
  goToDetection(ev: DetectionEvent): void {
    const rec = this.selectedRecording();
    const v = this.recEl;
    if (!rec || !v) return;
    const off = (new Date(ev.start).getTime() - new Date(rec.start).getTime()) / 1000;
    v.currentTime = Math.max(0, off);
    v.play();
    this.recPlaying.set(true);
  }
  /** Detection positions on the seek bar (percent along the segment + seconds). */
  detectionMarkers(): { file: string; pct: number; time: number }[] {
    const rec = this.selectedRecording();
    const d = this.recDuration();
    if (!rec || !d) return [];
    const start = new Date(rec.start).getTime();
    return this.eventsOf(rec.name).map((ev) => {
      const off = (new Date(ev.start).getTime() - start) / 1000;
      return { file: ev.file, pct: Math.max(0, Math.min(100, (off / d) * 100)), time: off };
    });
  }

  /** Bark events that fall inside a recording's 10-min window. */
  barksOf(recName: string): BarkEvent[] {
    const rec = this.recordings().find((r) => r.name === recName);
    if (!rec) return [];
    const cam = this.activeCamera();
    const s = new Date(rec.start).getTime();
    return this.barkEvents().filter((b) => {
      if (b.camera !== cam) return false;  // only this camera's barks
      const t = new Date(b.start).getTime();
      return t >= s && t < s + 10 * 60 * 1000;
    });
  }

  /** Bark positions on the seek bar (own color), % along the segment + seconds. */
  barkMarkers(): { ts: string; pct: number; time: number }[] {
    const rec = this.selectedRecording();
    const d = this.recDuration();
    if (!rec || !d) return [];
    const start = new Date(rec.start).getTime();
    return this.barksOf(rec.name).map((b) => {
      const off = (new Date(b.start).getTime() - start) / 1000;
      return { ts: b.ts, pct: Math.max(0, Math.min(100, (off / d) * 100)), time: off };
    });
  }

  /** Seek the current video to a bark's moment. */
  seekToBark(b: BarkEvent): void {
    const rec = this.selectedRecording();
    if (!rec) return;
    this.seekSeconds((new Date(b.start).getTime() - new Date(rec.start).getTime()) / 1000);
  }
  fmtClock(sec: number): string {
    sec = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  /** A recording older than the web-copy window (7 days) won't get a browser copy,
   *  so it's download-only (4K). Used to show "archivada" instead of "procesando". */
  isArchived(startISO: string): boolean {
    return Date.now() - new Date(startISO).getTime() > 7.5 * 24 * 60 * 60 * 1000;
  }

  /** Jump to a moment in the Garage recordings: switch tab, load its day, find the
   *  segment and seek to the second. Shared by person events and bark events. */
  private jumpToMoment(startISO: string, cam: CameraId = 'garage'): void {
    if (!this.isIpCam(cam)) {
      this.selectCamera(cam);  // greenhouse: live only, no recordings
      return;
    }
    const day = startISO.slice(0, 10);  // YYYY-MM-DD
    this.settings.set('cameraTab', cam);
    this.settings.set('cameraDay', day);
    this.pendingSeekStart.set(startISO);
    this.clearInterval();
    this.detachHls();
    this.activeCamera.set(cam);
    this.imgError.set(null);
    this.selectedRecording.set(null);
    this.garageLoading.set(true);
    this.loadEvents();
    if (cam === 'garage') {
      this.loadPresets();
      this.loadBarkEvents();
    }
    this.loadDays();  // restores `day` → loadRecordings → applies the pending seek
  }

  openEventInVideo(ev: DetectionEvent): void {
    this.jumpToMoment(ev.start, (ev.camera as CameraId) || 'garage');
  }

  openBarkInVideo(b: BarkEvent): void {
    this.jumpToMoment(b.start, (b.camera as CameraId) || 'garage');
  }

  // ─── Events gallery ────────────────────────────────────────────────────────

  loadEvents(): void {
    this.eventsError.set(null);
    this.http
      .get<DetectionEvent[]>(`${this.api}/api/cctv/events?limit=300`)
      .subscribe({
        next: (ev) => {
          this.events.set(ev);
          this.computeRecEvents();
        },
        error: () => this.eventsError.set('No se pudieron cargar los eventos.'),
      });
  }

  /** Correlate each recording segment with the detection events inside it. */
  private computeRecEvents(): void {
    const cam = this.activeCamera();
    // Only this camera's detections — otherwise a Garage detection would show up on
    // the Patio recording that happens to cover the same minute (and vice versa).
    const evs = this.events().filter((e) => e.camera === cam);
    const map: Record<string, DetectionEvent[]> = {};
    for (const rec of this.recordings()) {
      const start = new Date(rec.start).getTime();
      const end = start + 10 * 60 * 1000; // 10-min segment window
      map[rec.name] = evs.filter((e) => {
        const t = new Date(e.start).getTime();
        return t >= start && t < end;
      });
    }
    this.recEventsMap.set(map);
  }

  /** Detection events that fall inside a given recording. */
  eventsOf(name: string): DetectionEvent[] {
    return this.recEventsMap()[name] ?? [];
  }

  /** Number of person detections on the selected day (for the summary chip). */
  get dayEventsCount(): number {
    const d = this.selectedDay();
    const cam = this.activeCamera();
    return this.events().filter((e) => e.camera === cam && e.start.startsWith(d)).length;
  }

  /** Number of the day's recordings already backed up to R2. */
  get dayBackedCount(): number {
    return this.recordings().filter((r) => r.backed_up).length;
  }

  /** Human label for a camera id (e.g. 'patiopapas' → 'Patio Papás'). */
  camLabel(id: string): string {
    return this.tabs.find((t) => t.id === id)?.label ?? id;
  }

  eventImg(file: string): string {
    return `${this.api}/api/cctv/events/img/${file}`;
  }

  /** Small cached thumbnail for gallery/list previews (full image on click). */
  eventThumb(file: string): string {
    return `${this.api}/api/cctv/events/img/${file}?thumb=1`;
  }

  // ─── Ladridos (bark detection — calibración) ────────────────────────────────
  barkEvents    = signal<BarkEvent[]>([]);
  barkThreshold = signal<number>(0.3);
  barkError     = signal<string | null>(null);

  loadBarkEvents(): void {
    this.barkError.set(null);
    this.http.get<BarkEvent[]>(`${this.api}/api/cctv/bark/events?limit=300`).subscribe({
      next: (ev) => this.barkEvents.set(ev),
      error: () => this.barkError.set('No se pudieron cargar los ladridos.'),
    });
  }

  loadBarkThreshold(): void {
    this.http.get<{ threshold: number }>(`${this.api}/api/cctv/bark/threshold`).subscribe({
      next: (r) => this.barkThreshold.set(r.threshold ?? 0.3),
      error: () => {},
    });
  }

  onBarkThresholdChange(ev: Event): void {
    const v = Number((ev.target as HTMLInputElement).value);
    this.barkThreshold.set(v);
    this.http.post(`${this.api}/api/cctv/bark/threshold`, { threshold: v }).subscribe({ error: () => {} });
  }

  barkClip(file: string): string {
    return `${this.api}/api/cctv/bark/clip/${file}`;
  }
  barkImg(img: string): string {
    return `${this.api}/api/cctv/bark/img/${img}`;
  }
  /** How many logged barks would fire an alert at the current threshold. */
  get barkAboveCount(): number {
    const t = this.barkThreshold();
    return this.barkEvents().filter((b) => b.score >= t).length;
  }

  openLightbox(url: string): void {
    this.lightboxImg.set(url);
  }

  closeLightbox(): void {
    this.lightboxImg.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.lightboxImg()) {
      this.closeLightbox();
    }
  }

  formatDateTime(iso: string): string {
    // "2026-11-17T20:24:51" → "17/11 20:24:51"
    try {
      const [d, t] = iso.split('T');
      const [, mo, da] = d.split('-');
      return `${da}/${mo} ${t}`;
    } catch {
      return iso;
    }
  }

  // ─── Formatting helpers ───────────────────────────────────────────────────

  formatTime(isoDatetime: string): string {
    // "2026-11-17T09:43:00" → "09:43:00"
    try {
      return isoDatetime.substring(11, 19);
    } catch {
      return isoDatetime;
    }
  }

  formatSizeMB(bytes: number): string {
    return (bytes / 1_048_576).toFixed(1);
  }
}
