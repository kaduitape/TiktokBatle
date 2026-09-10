import { API_BASE } from "../../../api/client";

interface MixerVolumes {
  music: number;
  shots: number;
  explosions: number;
  alerts: number;
  ui: number;
  victory: number;
}

interface MusicTrackData {
  id: string;
  name: string;
  file_url: string;
  category: "normal" | "danger" | "victory" | "defeat";
  order_index: number;
}

const DEFAULT_MIXER: MixerVolumes = { music: 30, shots: 80, explosions: 80, alerts: 70, ui: 50, victory: 80 };

function resolveUrl(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE}${url}`;
}

/** Spec sections 31-34: playlist BGM per mood + a per-channel mixer.
 * No sound asset files ship with this repo, so gift/combo SFX are
 * synthesized on the fly with the Web Audio API -- real uploaded audio
 * (via the admin Músicas page) drives the BGM layer, which is the part
 * that actually needs licensed/uploaded content. */
export class AudioManager {
  private ctx: AudioContext | null = null;
  private mixer: MixerVolumes = DEFAULT_MIXER;
  private tracksByCategory: Partial<Record<string, MusicTrackData[]>> = {};
  private currentAudio: HTMLAudioElement | null = null;
  private currentCategory: string | null = null;
  private trackIndex: Record<string, number> = {};
  private unlockBound = false;

  async init(): Promise<void> {
    try {
      const res = await fetch(`${API_BASE}/api/settings/audio_mixer`);
      if (res.ok) this.mixer = { ...DEFAULT_MIXER, ...(await res.json()) };
    } catch {
      /* keep defaults */
    }

    try {
      const res = await fetch(`${API_BASE}/api/music`);
      if (res.ok) {
        const tracks: MusicTrackData[] = await res.json();
        for (const t of tracks) {
          (this.tracksByCategory[t.category] ||= []).push(t);
        }
      }
    } catch {
      /* no music configured -- arena still works silently */
    }

    try {
      const AudioContextCtor = window.AudioContext || (window as any).webkitAudioContext;
      this.ctx = new AudioContextCtor();
    } catch {
      this.ctx = null;
    }

    this.playCategory("normal");

    if (!this.unlockBound) {
      this.unlockBound = true;
      const unlock = () => {
        this.ctx?.resume().catch(() => {});
        this.currentAudio?.play().catch(() => {});
      };
      window.addEventListener("pointerdown", unlock);
      window.addEventListener("keydown", unlock);
    }
  }

  playCategory(category: string): void {
    if (this.currentCategory === category) return;
    this.currentCategory = category;

    const list = this.tracksByCategory[category];
    this.fadeOutCurrent();
    if (!list || !list.length) return;

    const idx = (this.trackIndex[category] || 0) % list.length;
    this.trackIndex[category] = idx + 1;
    const track = list[idx];

    const audio = new Audio(resolveUrl(track.file_url));
    audio.loop = list.length === 1;
    audio.volume = 0;
    audio.play().catch(() => {
      /* blocked by autoplay policy until the first user gesture */
    });
    this.currentAudio = audio;
    this.fadeTo(audio, this.mixer.music / 100, 800);

    if (list.length > 1) {
      audio.addEventListener("ended", () => {
        if (this.currentAudio === audio) this.playCategory(category);
      });
    }
  }

  private fadeOutCurrent(): void {
    const prev = this.currentAudio;
    this.currentAudio = null;
    if (!prev) return;
    this.fadeTo(prev, 0, 500, () => prev.pause());
  }

  private fadeTo(audio: HTMLAudioElement, target: number, duration: number, onDone?: () => void): void {
    const start = audio.volume;
    const startTime = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - startTime) / duration);
      audio.volume = start + (target - start) * t;
      if (t < 1) requestAnimationFrame(step);
      else onDone?.();
    };
    requestAnimationFrame(step);
  }

  /** Spec section 33: XP < 25% -> tensão, XP < 10% -> mais perigo. */
  updateDanger(pctA: number, pctB: number, hasWinner: boolean): void {
    if (hasWinner) {
      this.playCategory("victory");
      return;
    }
    const minPct = Math.min(pctA, pctB);
    this.playCategory(minPct <= 0.25 ? "danger" : "normal");
  }

  // ---- synthesized SFX ----

  private tone(freq: number, duration: number, channel: keyof MixerVolumes, type: OscillatorType = "sine", gainScale = 0.25): void {
    if (!this.ctx) return;
    const vol = this.mixer[channel] / 100;
    if (vol <= 0) return;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    const now = this.ctx.currentTime;
    gain.gain.setValueAtTime(vol * gainScale, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + duration);
    osc.connect(gain).connect(this.ctx.destination);
    osc.start(now);
    osc.stop(now + duration);
  }

  private noiseBurst(duration: number, channel: keyof MixerVolumes, gainScale = 0.3): void {
    if (!this.ctx) return;
    const vol = this.mixer[channel] / 100;
    if (vol <= 0) return;
    const bufferSize = Math.floor(this.ctx.sampleRate * duration);
    const buffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / bufferSize);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    const gain = this.ctx.createGain();
    gain.gain.value = vol * gainScale;
    src.connect(gain).connect(this.ctx.destination);
    src.start();
  }

  shot(): void {
    this.tone(880, 0.08, "shots", "square", 0.15);
  }

  missile(): void {
    this.noiseBurst(0.35, "explosions", 0.35);
    this.tone(90, 0.3, "explosions", "sawtooth", 0.2);
  }

  heal(): void {
    this.tone(660, 0.25, "alerts", "sine", 0.2);
    this.tone(880, 0.2, "alerts", "sine", 0.15);
  }

  combo(): void {
    this.tone(520, 0.15, "alerts", "triangle", 0.2);
  }

  victoryFanfare(): void {
    [523, 659, 784, 1046].forEach((f, i) => setTimeout(() => this.tone(f, 0.3, "victory", "triangle", 0.25), i * 140));
  }
}
