import { useState } from 'react';
import { Mic, MicOff, Volume2, VolumeX, Volume1 } from 'lucide-react';
import { motion } from 'motion/react';

export function AudioControls() {
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(50);

  const VolumeIcon = volume === 0 ? VolumeX : volume < 50 ? Volume1 : Volume2;

  return (
    <div className="absolute left-6 top-1/2 -translate-y-1/2 flex flex-col items-center gap-6 z-20">
      <motion.button
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setMuted(!muted)}
        className={`w-16 h-16 rounded-full flex items-center justify-center transition-colors backdrop-blur-md border ${
          muted 
            ? 'bg-red-500/20 border-red-500/50 text-red-200' 
            : 'bg-white/10 border-white/20 text-white hover:bg-white/20'
        }`}
      >
        {muted ? <MicOff size={28} /> : <Mic size={28} />}
      </motion.button>

      <div className="flex flex-col items-center gap-4 bg-white/5 p-4 rounded-full border border-white/10 backdrop-blur-md">
        <VolumeIcon size={24} className="text-white/70" />
        <div className="h-32 w-10 flex items-center justify-center relative">
          <input
            type="range"
            min="0"
            max="100"
            value={volume}
            onChange={(e) => setVolume(Number(e.target.value))}
            className="absolute w-32 h-2 -rotate-90 appearance-none bg-white/20 rounded-full outline-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-lg"
          />
        </div>
      </div>
    </div>
  );
}
