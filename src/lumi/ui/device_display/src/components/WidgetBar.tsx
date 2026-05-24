import { useEffect, useState } from 'react';
import { motion } from 'motion/react';
import { Calendar, Cloud, CloudRain, CloudSnow, Cpu, Moon, Sun } from 'lucide-react';
import type { WeatherSnapshot } from '../state';

interface WidgetBarProps {
  weather: WeatherSnapshot | null;
  cpuPct: number;
}

export function WidgetBar({ weather, cpuPct }: WidgetBarProps) {
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);

  const timeStr = now.toLocaleTimeString('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const [timePart, ampm = ''] = timeStr.split(' ');
  const dateStr = now.toLocaleDateString('en-US', {
    weekday: 'long', month: 'short', day: 'numeric',
  });
  const [weekday, datePart = ''] = dateStr.split(',').map((s) => s.trim());

  return (
    <div className="w-full bg-gradient-to-r from-indigo-500/20 to-purple-500/20 backdrop-blur-sm px-4 py-3 border-t border-white/10">
      <div className="grid grid-cols-4 gap-3 text-center">
        {/* Time */}
        <div className="flex flex-col items-center gap-1">
          <div className="text-xl font-bold text-white tabular-nums tracking-tight">
            {timePart}
          </div>
          <div className="text-xs text-white/60 uppercase">{ampm}</div>
        </div>

        {/* Date */}
        <div className="flex flex-col items-center gap-1">
          <Calendar className="w-4 h-4 text-blue-300" />
          <div className="text-xs font-medium text-white">{weekday}</div>
          <div className="text-xs text-white/60">{datePart}</div>
        </div>

        {/* Weather */}
        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center gap-2">
            <WeatherIcon condition={weather?.condition} />
            <span className="text-lg font-bold text-white">
              {weather ? `${Math.round(weather.tempC)}°` : '—'}
            </span>
          </div>
          <div className="text-xs text-white/60 capitalize">
            {weather?.condition ?? 'weather off'}
          </div>
        </div>

        {/* CPU */}
        <div className="flex flex-col items-center gap-1">
          <Cpu className="w-4 h-4 text-green-300" />
          <div className="text-xs font-medium text-white">{cpuPct}%</div>
          <div className="w-12 h-1 bg-white/20 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-gradient-to-r from-green-400 to-blue-400"
              initial={{ width: 0 }}
              animate={{ width: `${Math.min(100, Math.max(0, cpuPct))}%` }}
              transition={{ duration: 0.8 }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function WeatherIcon({ condition }: { condition?: WeatherSnapshot['condition'] }) {
  switch (condition) {
    case 'sunny':       return <Sun className="w-5 h-5 text-yellow-400" />;
    case 'clear-night': return <Moon className="w-5 h-5 text-indigo-200" />;
    case 'cloudy':      return <Cloud className="w-5 h-5 text-gray-300" />;
    case 'rainy':       return <CloudRain className="w-5 h-5 text-blue-400" />;
    case 'snowy':       return <CloudSnow className="w-5 h-5 text-cyan-200" />;
    default:            return <Cloud className="w-5 h-5 text-white/30" />;
  }
}
