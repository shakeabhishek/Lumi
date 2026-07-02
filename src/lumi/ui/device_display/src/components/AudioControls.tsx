import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, Volume2, VolumeX, Volume1 } from 'lucide-react';
import { motion } from 'motion/react';

interface AudioControlsProps {
  micMuted: boolean;
  volume: number;
}

function postForm(path: string, fields: Record<string, string>): void {
  fetch(path, { method: 'POST', body: new URLSearchParams(fields) }).catch(() => {
    // Best-effort — if this fails the next SSE snapshot still reflects
    // whatever the hardware's actual state is, so the UI self-heals.
  });
}

export function AudioControls({ micMuted, volume }: AudioControlsProps) {
  const [localVolume, setLocalVolume] = useState(volume);
  const draggingRef = useRef(false);

  // Follow the server's real value (pushed over SSE) — except mid-drag,
  // where snapping the thumb back to a lagging echo would feel broken.
  useEffect(() => {
    if (!draggingRef.current) {
      setLocalVolume(volume);
    }
  }, [volume]);

  const volumeFromPointer = (e: React.PointerEvent<HTMLDivElement>): number => {
    const rect = e.currentTarget.getBoundingClientRect();
    const y = rect.bottom - e.clientY;
    return Math.min(100, Math.max(0, Math.round((y / rect.height) * 100)));
  };

  const toggleMicMuted = () => {
    postForm('/device-display/audio/mute', { muted: String(!micMuted) });
  };

  const VolumeIcon = localVolume === 0 ? VolumeX : localVolume < 50 ? Volume1 : Volume2;

  return (
    <div className="absolute left-6 top-1/2 -translate-y-1/2 flex flex-col items-center gap-6 z-20">
      <motion.button
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        onClick={toggleMicMuted}
        aria-label={micMuted ? 'Unmute microphone' : 'Mute microphone'}
        className={`w-16 h-16 rounded-full flex items-center justify-center transition-colors backdrop-blur-md border ${
          micMuted
            ? 'bg-red-500/20 border-red-500/50 text-red-200'
            : 'bg-white/10 border-white/20 text-white hover:bg-white/20'
        }`}
      >
        {micMuted ? <MicOff size={28} /> : <Mic size={28} />}
      </motion.button>

      <div className="flex flex-col items-center gap-4 bg-white/5 p-4 rounded-full border border-white/10 backdrop-blur-md">
        <VolumeIcon size={24} className="text-white/70" />
        <div
          className="h-32 w-10 flex justify-center relative cursor-pointer"
          style={{ touchAction: 'none' }}
          onPointerDown={(e) => {
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
            draggingRef.current = true;
            setLocalVolume(volumeFromPointer(e));
          }}
          onPointerMove={(e) => {
            if (e.buttons === 1) {
              setLocalVolume(volumeFromPointer(e));
            }
          }}
          onPointerUp={(e) => {
            (e.target as HTMLElement).releasePointerCapture(e.pointerId);
            const final = volumeFromPointer(e);
            setLocalVolume(final);
            postForm('/device-display/audio/volume', { volume: String(final) });
            draggingRef.current = false;
          }}
        >
          <div className="absolute bottom-0 w-2 bg-white/20 rounded-full h-full" />
          <div
            className="absolute bottom-0 w-2 bg-white rounded-full"
            style={{ height: `${localVolume}%` }}
          />
          <div
            className="absolute w-5 h-5 bg-white rounded-full shadow-lg pointer-events-none"
            style={{ bottom: `calc(${localVolume}% - 10px)` }}
          />
        </div>
      </div>
    </div>
  );
}
