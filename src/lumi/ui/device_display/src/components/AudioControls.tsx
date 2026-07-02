import { useEffect, useRef, useState } from 'react';
import { Mic, MicOff, Volume2, VolumeX, Volume1, Sun } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

interface AudioControlsProps {
  micMuted: boolean;
  volume: number;
  brightness: number;
}

function postForm(path: string, fields: Record<string, string>): void {
  fetch(path, { method: 'POST', body: new URLSearchParams(fields) }).catch(() => {
    // Best-effort — if this fails the next SSE snapshot still reflects
    // whatever the hardware's actual state is, so the UI self-heals.
  });
}

export function AudioControls({ micMuted, volume, brightness }: AudioControlsProps) {
  const [localMuted, setLocalMuted] = useState(micMuted);

  // Sync with server state when it arrives
  useEffect(() => {
    setLocalMuted(micMuted);
  }, [micMuted]);

  const toggleMicMuted = () => {
    const nextMuted = !localMuted;
    setLocalMuted(nextMuted); // Optimistic UI update
    postForm('/device-display/audio/mute', { muted: String(nextMuted) });
  };

  return (
    <div className="absolute left-6 top-1/2 -translate-y-1/2 flex flex-col items-center gap-6 z-20">
      <motion.button
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        onClick={toggleMicMuted}
        aria-label={localMuted ? 'Unmute microphone' : 'Mute microphone'}
        className={`w-16 h-16 rounded-full flex items-center justify-center transition-colors backdrop-blur-md border shadow-xl ${
          localMuted
            ? 'bg-red-500/20 border-red-500/50 text-red-200'
            : 'bg-white/10 border-white/20 text-white hover:bg-white/20'
        }`}
      >
        {localMuted ? <MicOff size={28} /> : <Mic size={28} />}
      </motion.button>

      <CollapsibleSlider
        type="volume"
        initialValue={volume}
        onChange={(v) => postForm('/device-display/audio/volume', { volume: String(v) })}
      />
      
      <CollapsibleSlider
        type="brightness"
        initialValue={brightness}
        onChange={(v) => postForm('/device-display/system/brightness', { brightness: String(v) })}
      />
    </div>
  );
}

// While dragging, commit to hardware at most this often — live enough to
// feel real-time, throttled enough not to fire a POST (and an amixer
// subprocess, for the volume slider) on every single pointermove event.
const DRAG_COMMIT_THROTTLE_MS = 80;

function CollapsibleSlider({
  type,
  initialValue,
  onChange
}: {
  type: 'volume' | 'brightness',
  initialValue: number,
  onChange: (v: number) => void
}) {
  const [value, setValue] = useState(initialValue);
  const [expanded, setExpanded] = useState(false);
  const draggingRef = useRef(false);
  const collapseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastCommitRef = useRef(0);

  useEffect(() => {
    if (!draggingRef.current) setValue(initialValue);
  }, [initialValue]);

  const startCollapseTimer = () => {
    if (collapseTimeoutRef.current) clearTimeout(collapseTimeoutRef.current);
    collapseTimeoutRef.current = setTimeout(() => {
      setExpanded(false);
    }, 2000);
  };

  const clearCollapseTimer = () => {
    if (collapseTimeoutRef.current) clearTimeout(collapseTimeoutRef.current);
  };

  const valFromPointer = (e: React.PointerEvent<HTMLDivElement>): number => {
    const rect = e.currentTarget.getBoundingClientRect();
    const y = rect.bottom - e.clientY;
    return Math.min(100, Math.max(0, Math.round((y / rect.height) * 100)));
  };

  const Icon = type === 'volume' 
    ? (value === 0 ? VolumeX : value < 50 ? Volume1 : Volume2)
    : Sun;

  return (
    <motion.div
      className="flex flex-col items-center bg-white/5 border border-white/10 backdrop-blur-md rounded-full shadow-xl"
      animate={{ padding: expanded ? '16px' : '16px' }}
      initial={false}
    >
      <div 
        className="cursor-pointer p-2 -m-2" 
        onClick={() => {
          if (expanded) {
            setExpanded(false);
            clearCollapseTimer();
          } else {
            setExpanded(true);
            startCollapseTimer();
          }
        }}
      >
        <Icon size={28} className="text-white/70" />
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0, marginTop: 0 }}
            animate={{ height: 128, opacity: 1, marginTop: 16 }}
            exit={{ height: 0, opacity: 0, marginTop: 0 }}
            transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }}
            className="w-10 flex justify-center relative cursor-pointer"
            style={{ touchAction: 'none' }}
            onPointerDown={(e) => {
              (e.target as HTMLElement).setPointerCapture(e.pointerId);
              draggingRef.current = true;
              clearCollapseTimer();
              const v = valFromPointer(e);
              setValue(v);
              onChange(v);
              lastCommitRef.current = performance.now();
            }}
            onPointerMove={(e) => {
              if (e.buttons !== 1) return;
              const v = valFromPointer(e);
              setValue(v);
              const now = performance.now();
              if (now - lastCommitRef.current >= DRAG_COMMIT_THROTTLE_MS) {
                lastCommitRef.current = now;
                onChange(v);
              }
            }}
            onPointerUp={(e) => {
              (e.target as HTMLElement).releasePointerCapture(e.pointerId);
              const final = valFromPointer(e);
              setValue(final);
              onChange(final); // always commit the exact final position
              draggingRef.current = false;
              startCollapseTimer();
            }}
          >
            <div className="absolute bottom-0 w-2 bg-white/20 rounded-full h-full pointer-events-none" />
            <div
              className="absolute bottom-0 w-2 bg-white rounded-full pointer-events-none"
              style={{ height: `${value}%` }}
            />
            <div
              className="absolute w-5 h-5 bg-white rounded-full shadow-lg pointer-events-none"
              style={{ bottom: `calc(${value}% - 10px)` }}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
