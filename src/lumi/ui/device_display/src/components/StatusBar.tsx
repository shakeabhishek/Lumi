import { motion } from 'motion/react';
import { Cloud, Wifi, WifiOff, Battery } from 'lucide-react';

interface StatusBarProps {
  connected: boolean;
  statusText: string;
}

export function StatusBar({ connected, statusText }: StatusBarProps) {
  return (
    <div className="w-full bg-gradient-to-r from-purple-500/20 to-pink-500/20 backdrop-blur-sm px-4 py-2 flex items-center justify-between border-b border-white/10">
      <div className="flex items-center gap-2">
        {connected ? (
          <motion.div
            animate={{ opacity: [0.55, 1, 0.55] }}
            transition={{ duration: 2, repeat: Infinity }}
          >
            <Wifi className="w-4 h-4 text-green-400" />
          </motion.div>
        ) : (
          <WifiOff className="w-4 h-4 text-rose-300/80" />
        )}
        <span className="text-xs text-white/85">{statusText}</span>
      </div>
      <div className="flex items-center gap-3">
        <Cloud className="w-4 h-4 text-blue-300" />
        <Battery className="w-4 h-4 text-green-400" />
      </div>
    </div>
  );
}
