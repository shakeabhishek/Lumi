import { useState, useEffect } from 'react';
import { motion } from 'motion/react';

export function AmbientBackground() {
  const [hour, setHour] = useState(new Date().getHours());

  useEffect(() => {
    const tick = setInterval(() => setHour(new Date().getHours()), 60000); // Check every minute
    return () => clearInterval(tick);
  }, []);

  // Determine color palette based on hour of day
  let palette = {
    color1: '#0f172a', // slate-900
    color2: '#1e1b4b', // indigo-950
    color3: '#312e81', // indigo-800
  };

  if (hour >= 5 && hour < 8) {
    // Sunrise (Dark aesthetic)
    palette = { color1: '#5b21b6', color2: '#7e22ce', color3: '#be185d' }; // violet-800, purple-700, pink-700
  } else if (hour >= 8 && hour < 17) {
    // Day (Dark aesthetic)
    palette = { color1: '#0369a1', color2: '#1d4ed8', color3: '#0f766e' }; // sky-700, blue-700, teal-700
  } else if (hour >= 17 && hour < 20) {
    // Sunset (Dark aesthetic)
    palette = { color1: '#9a3412', color2: '#a21caf', color3: '#86198f' }; // orange-800, fuchsia-700, fuchsia-800
  }

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none -z-10 bg-[#050505]">
      <motion.div
        className="absolute -inset-[50%] opacity-50 filter blur-[120px]"
        animate={{
          background: [
            `radial-gradient(circle at 0% 0%, ${palette.color1}, transparent 50%), radial-gradient(circle at 100% 100%, ${palette.color3}, transparent 50%), radial-gradient(circle at 100% 0%, ${palette.color2}, transparent 50%)`,
            `radial-gradient(circle at 100% 0%, ${palette.color1}, transparent 50%), radial-gradient(circle at 0% 100%, ${palette.color3}, transparent 50%), radial-gradient(circle at 0% 0%, ${palette.color2}, transparent 50%)`,
            `radial-gradient(circle at 100% 100%, ${palette.color1}, transparent 50%), radial-gradient(circle at 0% 0%, ${palette.color3}, transparent 50%), radial-gradient(circle at 0% 100%, ${palette.color2}, transparent 50%)`,
            `radial-gradient(circle at 0% 100%, ${palette.color1}, transparent 50%), radial-gradient(circle at 100% 0%, ${palette.color3}, transparent 50%), radial-gradient(circle at 100% 100%, ${palette.color2}, transparent 50%)`,
            `radial-gradient(circle at 0% 0%, ${palette.color1}, transparent 50%), radial-gradient(circle at 100% 100%, ${palette.color3}, transparent 50%), radial-gradient(circle at 100% 0%, ${palette.color2}, transparent 50%)`,
          ]
        }}
        transition={{
          duration: 30,
          repeat: Infinity,
          ease: "linear"
        }}
      />
    </div>
  );
}
