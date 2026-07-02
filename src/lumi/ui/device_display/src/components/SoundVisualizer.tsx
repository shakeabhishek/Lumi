import { motion } from 'motion/react';

/**
 * Twelve gradient bars that pulse while Lumi is speaking. Lifted from
 * the Figma export and slightly toned down (warmer pink → purple, no
 * neon). Renders below the face area only during the SPEAK state.
 */
export function SoundVisualizer() {
  return (
    <div className="absolute bottom-0 left-0 right-0 flex items-end justify-center h-48 pointer-events-none z-0 px-20 pb-4 overflow-hidden mask-image:linear-gradient(to_right,transparent,black_20%,black_80%,transparent)">
      <div className="flex items-end justify-center gap-1.5 w-full max-w-5xl opacity-50">
        {Array.from({ length: 64 }).map((_, i) => (
          <motion.div
            key={i}
            className="flex-1 max-w-[8px] bg-gradient-to-t from-pink-500 via-purple-500 to-indigo-500 rounded-t-full shadow-[0_0_15px_rgba(219,39,119,0.5)]"
            animate={{ 
              height: [
                `${Math.random() * 20 + 10}%`, 
                `${Math.random() * 60 + 40}%`, 
                `${Math.random() * 30 + 10}%`, 
                `${Math.random() * 90 + 30}%`, 
                `${Math.random() * 20 + 10}%`
              ] 
            }}
            transition={{
              duration: Math.random() * 0.5 + 0.4,
              repeat: Infinity,
              delay: i * 0.02,
              ease: 'easeInOut',
            }}
          />
        ))}
      </div>
    </div>
  );
}
