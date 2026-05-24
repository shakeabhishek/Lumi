import { useEffect, useMemo, useRef, useState } from 'react';

/**
 * SpriteSceneFace — plays a frame-loop from one of Lumi's bundled or
 * user-uploaded sprite packs. The backend exposes
 *   /device-display/sprite/<pack>/frame_NNN.png
 * for both bundled (src/lumi/ui/face/assets/sprites/) and user
 * (data_dir/sprites/) packs, with the existing override semantics:
 * user-uploaded packs with the same name win.
 *
 * The manifest.json at the pack root governs the fps + bg. We probe
 * it on mount; if it's missing we fall back to 6 fps + transparent.
 */
export function SpriteSceneFace({ packName }: { packName: string }) {
  const [manifest, setManifest] = useState<Manifest>({ fps: 6, frames: 0, background: 'transparent' });
  const [frame, setFrame] = useState(0);
  const tickRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`/device-display/sprite/${encodeURIComponent(packName)}/manifest.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => {
        if (cancelled || !m) return;
        setManifest({
          fps: Number(m.fps ?? 6),
          frames: Number(m.frames ?? 0),
          background: typeof m.background === 'string' ? m.background : 'transparent',
        });
      })
      .catch(() => { /* keep defaults */ });
    return () => { cancelled = true; };
  }, [packName]);

  useEffect(() => {
    if (manifest.frames <= 0) return;
    const interval = setInterval(() => {
      setFrame((f) => (f + 1) % manifest.frames);
    }, 1000 / manifest.fps);
    tickRef.current = interval as unknown as number;
    return () => clearInterval(interval);
  }, [manifest.fps, manifest.frames]);

  const src = useMemo(
    () => `/device-display/sprite/${encodeURIComponent(packName)}/frame_${String(frame).padStart(3, '0')}.png`,
    [packName, frame],
  );

  if (manifest.frames === 0) {
    return (
      <div className="w-[460px] h-[260px] flex items-center justify-center text-white/60 text-sm font-mono">
        sprite pack &quot;{packName}&quot; has no frames yet
      </div>
    );
  }

  return (
    <div
      className="w-[460px] h-[260px] flex items-center justify-center rounded-xl overflow-hidden"
      style={{ background: manifest.background }}
    >
      <img
        src={src}
        alt={`${packName} idle scene`}
        className="max-w-full max-h-full"
        style={{ imageRendering: 'pixelated' }}
      />
    </div>
  );
}

interface Manifest {
  fps: number;
  frames: number;
  background: string;
}
