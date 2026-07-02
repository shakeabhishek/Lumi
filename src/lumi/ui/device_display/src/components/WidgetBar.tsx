import { motion } from 'motion/react';
import { Cpu, MemoryStick, Thermometer } from 'lucide-react';

interface WidgetBarProps {
  cpuPct: number;
  memPct: number;
  cpuTempC: number;
}

// SoC temp colour: green < 60°C, amber 60–74°C, red ≥ 75°C (Pi throttles ~80°C).
function tempColor(t: number): string {
  if (t >= 75) return 'text-red-400';
  if (t >= 60) return 'text-amber-300';
  return 'text-orange-300';
}

export function WidgetBar({ cpuPct, memPct, cpuTempC }: WidgetBarProps) {
  return (
    <div className="w-full flex justify-center gap-6 mt-4">
      {/* CPU Tile */}
      <div className="bg-white/5 border border-white/10 backdrop-blur-md rounded-3xl p-5 flex flex-col items-center justify-center min-w-[140px] shadow-xl gap-2">
        <div className="flex items-center gap-2">
          <Cpu className="w-5 h-5 text-green-300" />
          <span className="text-lg font-bold text-white">{cpuPct}%</span>
        </div>
        <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden mt-1">
          <motion.div
            className="h-full bg-gradient-to-r from-green-400 to-blue-400"
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, Math.max(0, cpuPct))}%` }}
            transition={{ duration: 0.8 }}
          />
        </div>
        <div className="text-xs text-white/50 uppercase tracking-widest font-semibold">CPU</div>
      </div>

      {/* RAM Tile */}
      <div className="bg-white/5 border border-white/10 backdrop-blur-md rounded-3xl p-5 flex flex-col items-center justify-center min-w-[140px] shadow-xl gap-2">
        <div className="flex items-center gap-2">
          <MemoryStick className="w-5 h-5 text-purple-300" />
          <span className="text-lg font-bold text-white">{memPct}%</span>
        </div>
        <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden mt-1">
          <motion.div
            className="h-full bg-gradient-to-r from-purple-400 to-pink-400"
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, Math.max(0, memPct))}%` }}
            transition={{ duration: 0.8 }}
          />
        </div>
        <div className="text-xs text-white/50 uppercase tracking-widest font-semibold">RAM</div>
      </div>

      {/* Temp Tile */}
      <div className="bg-white/5 border border-white/10 backdrop-blur-md rounded-3xl p-5 flex flex-col items-center justify-center min-w-[140px] shadow-xl gap-2">
        <div className="flex items-center gap-2">
          <Thermometer className={`w-5 h-5 ${tempColor(cpuTempC)}`} />
          <span className="text-lg font-bold text-white">{cpuTempC ? `${cpuTempC}°C` : '—'}</span>
        </div>
        <div className="w-24 h-1.5 bg-white/10 rounded-full overflow-hidden mt-1">
          <motion.div
            className="h-full bg-gradient-to-r from-orange-400 to-red-400"
            initial={{ width: 0 }}
            animate={{ width: `${Math.min(100, Math.max(0, (cpuTempC / 85) * 100))}%` }}
            transition={{ duration: 0.8 }}
          />
        </div>
        <div className="text-xs text-white/50 uppercase tracking-widest font-semibold">Temp</div>
      </div>
    </div>
  );
}


