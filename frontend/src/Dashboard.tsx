import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

interface DashboardProps {
  onLogout?: () => void;
  onNavigate?: (appId: string) => void;
}

type Mode = 'PAPER' | 'LIVE';
type KillSwitchState = 'HEALTHY' | 'TRIPPED';
type SignalResult = 'LONG' | 'SHORT' | 'NONE';
type AiDecision = 'PROCEED' | 'VETOED';
type ExitMode = 'SCALP MODE' | 'HOLD MODE';
type TradeStatus = 'WIN' | 'LOSS' | 'OPEN' | 'CANCELLED';
type TabletTab = 'SYSTEM' | 'AI';

interface PositionState {
  open: boolean;
  token: 'BTC UP' | 'BTC DOWN';
  entryPrice: number;
  currentPrice: number;
  unrealizedPnl: number;
  holdSeconds: number;
  exitMode: ExitMode;
}

interface DailyState {
  tradesUsed: number;
  tradeLimit: number;
  winRate: number;
  netPnl: number;
  dailyLossUsed: number;
  dailyLossLimit: number;
}

interface RiskState {
  cooldownSeconds: number;
  maxTradeSize: number;
  dailyLossRemaining: number;
  dailyLossCap: number;
  openSlots: number;
  maxSlots: number;
}

interface SignalState {
  rsi: number;
  rsiPrev: number;
  rsiSeries: number[];
  stochK: number;
  stochD: number;
  stochKSeries: number[];
  stochDSeries: number[];
  result: SignalResult;
}

interface AiState {
  enabled: boolean;
  decision: AiDecision;
  probability: number;
  marketPrice: number;
  edge: number;
  confidence: number;
  positionFactor: number;
  latencySeconds: number;
  warningFlags: string[];
  reasoning: string;
  totalDecisions: number;
  vetoRate: number;
  avgLatency: number;
  accuracy: number;
  consecutiveFailures: number;
}

interface MarketState {
  slug: string;
  candleOpen: string;
  candleClose: string;
  remainingSeconds: number;
  spreadCents: number;
  upPriceCents: number;
  downPriceCents: number;
  resolutionSource: string;
}

interface TradeRow {
  time: string;
  direction: 'UP' | 'DOWN';
  entry: number;
  exit: number | null;
  size: number;
  pnl: number | null;
  status: TradeStatus;
  exitReason: string;
  mode: 'SCALP' | 'HOLD';
}

interface PnlPoint {
  time: string;
  pnl: number;
  trade?: boolean;
}

interface DashboardState {
  mode: Mode;
  killSwitch: KillSwitchState;
  position: PositionState;
  daily: DailyState;
  risk: RiskState;
  signal: SignalState;
  ai: AiState;
  market: MarketState;
  pnlSeries: PnlPoint[];
  tradeLog: TradeRow[];
  systemLogs: string[];
}

interface NotificationItem {
  id: number;
  type: 'info' | 'win' | 'loss';
  message: string;
  detail: string;
}

const COLORS = {
  background: '#020408',
  panel: '#070D14',
  border: '#0D2137',
  cyan: '#00E5FF',
  green: '#00FF88',
  red: '#FF2D55',
  amber: '#FF9500',
  text: '#8BA8C4',
  bright: '#E0F4FF',
};

const PANEL_CLASS =
  'relative rounded-none border border-[#0D2137] bg-[#070D14]/95 p-3 shadow-[0_0_12px_rgba(13,33,55,0.85),inset_0_0_10px_rgba(0,229,255,0.06)]';

const MOCK_DASHBOARD: DashboardState = {
  mode: 'PAPER',
  killSwitch: 'HEALTHY',
  position: {
    open: true,
    token: 'BTC UP',
    entryPrice: 0.52,
    currentPrice: 0.56,
    unrealizedPnl: 0.77,
    holdSeconds: 8 * 60 + 34,
    exitMode: 'SCALP MODE',
  },
  daily: {
    tradesUsed: 2,
    tradeLimit: 6,
    winRate: 75,
    netPnl: 2.14,
    dailyLossUsed: 3.8,
    dailyLossLimit: 15,
  },
  risk: {
    cooldownSeconds: 4 * 60 + 12,
    maxTradeSize: 10,
    dailyLossRemaining: 11.2,
    dailyLossCap: 15,
    openSlots: 1,
    maxSlots: 1,
  },
  signal: {
    rsi: 32.4,
    rsiPrev: 28.1,
    rsiSeries: [24.6, 25.4, 26.8, 27.3, 28.1, 29.7, 31.1, 30.4, 32.4, 33.2, 31.9, 32.4],
    stochK: 24.3,
    stochD: 19.8,
    stochKSeries: [13.4, 14.9, 15.2, 16.1, 17.4, 18.8, 20.2, 22.6, 24.3],
    stochDSeries: [18.7, 18.4, 18.1, 17.8, 17.9, 18.4, 18.9, 19.2, 19.8],
    result: 'LONG',
  },
  ai: {
    enabled: true,
    decision: 'PROCEED',
    probability: 0.612,
    marketPrice: 0.52,
    edge: 0.09,
    confidence: 72,
    positionFactor: 0.9,
    latencySeconds: 1.24,
    warningFlags: ['NEAR_CLOSE', 'LOW_EDGE'],
    reasoning:
      'RSI crossed 30 with uptick in momentum. Slow Stoch K crossed above D in oversold zone. Spread remains below 2¢ and no kill-switch constraints active.',
    totalDecisions: 47,
    vetoRate: 23,
    avgLatency: 1.8,
    accuracy: 68,
    consecutiveFailures: 0,
  },
  market: {
    slug: 'btc-updown-1h-1739836800',
    candleOpen: '14:00 UTC',
    candleClose: '15:00 UTC',
    remainingSeconds: 51 * 60 + 26,
    spreadCents: 1.8,
    upPriceCents: 52,
    downPriceCents: 47.8,
    resolutionSource: 'Binance BTC/USDT',
  },
  pnlSeries: [
    { time: 'D-7 00:00', pnl: -1.1 },
    { time: 'D-6 06:00', pnl: -0.4, trade: true },
    { time: 'D-6 12:00', pnl: 0.8 },
    { time: 'D-5 00:00', pnl: 1.2 },
    { time: 'D-5 08:00', pnl: 2.9, trade: true },
    { time: 'D-5 16:00', pnl: 2.5 },
    { time: 'D-4 00:00', pnl: 3.1 },
    { time: 'D-4 10:00', pnl: 4.6, trade: true },
    { time: 'D-4 18:00', pnl: 4.1 },
    { time: 'D-3 04:00', pnl: 5.7 },
    { time: 'D-3 12:00', pnl: 6.3, trade: true },
    { time: 'D-2 00:00', pnl: 7.8 },
    { time: 'D-2 08:00', pnl: 8.6 },
    { time: 'D-2 16:00', pnl: 9.5, trade: true },
    { time: 'D-1 00:00', pnl: 10.1 },
    { time: 'D-1 10:00', pnl: 10.9 },
    { time: 'D-1 20:00', pnl: 11.4, trade: true },
    { time: 'NOW', pnl: 12.4 },
  ],
  tradeLog: [
    {
      time: '14:24:12',
      direction: 'UP',
      entry: 0.52,
      exit: null,
      size: 10,
      pnl: null,
      status: 'OPEN',
      exitReason: '—',
      mode: 'SCALP',
    },
    {
      time: '13:58:05',
      direction: 'UP',
      entry: 0.49,
      exit: 0.54,
      size: 10,
      pnl: 1.92,
      status: 'WIN',
      exitReason: 'PROFIT TARGET',
      mode: 'SCALP',
    },
    {
      time: '13:12:43',
      direction: 'DOWN',
      entry: 0.53,
      exit: 0.55,
      size: 8,
      pnl: -0.96,
      status: 'LOSS',
      exitReason: 'STOP LOSS',
      mode: 'HOLD',
    },
    {
      time: '12:48:17',
      direction: 'UP',
      entry: 0.47,
      exit: 0.52,
      size: 10,
      pnl: 1.37,
      status: 'WIN',
      exitReason: 'TRAIL EXIT',
      mode: 'SCALP',
    },
    {
      time: '12:09:09',
      direction: 'UP',
      entry: 0.51,
      exit: 0.49,
      size: 6,
      pnl: -0.68,
      status: 'LOSS',
      exitReason: 'STOP LOSS',
      mode: 'HOLD',
    },
    {
      time: '11:38:34',
      direction: 'DOWN',
      entry: 0.56,
      exit: 0.53,
      size: 7,
      pnl: 1.11,
      status: 'WIN',
      exitReason: 'TARGET HIT',
      mode: 'SCALP',
    },
    {
      time: '10:52:50',
      direction: 'UP',
      entry: 0.5,
      exit: 0.5,
      size: 0,
      pnl: 0,
      status: 'CANCELLED',
      exitReason: 'SPREAD SPIKE',
      mode: 'SCALP',
    },
    {
      time: '10:21:11',
      direction: 'DOWN',
      entry: 0.58,
      exit: 0.56,
      size: 10,
      pnl: 1.22,
      status: 'WIN',
      exitReason: 'TARGET HIT',
      mode: 'HOLD',
    },
  ],
  systemLogs: [
    '14:31:01 Signal evaluated: LONG',
    '14:30:01 Market context refreshed',
    '14:29:01 AI minimax pass: PROCEED',
    '14:28:01 Risk gates check: OK',
    '14:27:01 WS heartbeat stable',
  ],
};

const noiseTexture =
  "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='160' height='160' filter='url(%23n)' opacity='0.35'/%3E%3C/svg%3E\")";

function secondsToClock(total: number): string {
  const clamped = Math.max(0, total);
  const hours = Math.floor(clamped / 3600)
    .toString()
    .padStart(2, '0');
  const minutes = Math.floor((clamped % 3600) / 60)
    .toString()
    .padStart(2, '0');
  const seconds = Math.floor(clamped % 60)
    .toString()
    .padStart(2, '0');
  return `${hours}:${minutes}:${seconds}`;
}

function formatUtcClock(date: Date): string {
  return `UTC ${date.toLocaleTimeString('en-GB', {
    hour12: false,
    timeZone: 'UTC',
  })}`;
}

function formatDollar(value: number): string {
  return `${value >= 0 ? '+' : '-'}$${Math.abs(value).toFixed(2)}`;
}

function formatPrice(value: number): string {
  return `$${value.toFixed(2)}`;
}

function formatCents(value: number): string {
  return `${value.toFixed(1)}¢`;
}

function tradeStatusStyles(status: TradeStatus): { badge: string; line: string } {
  switch (status) {
    case 'WIN':
      return {
        badge: 'bg-[#00FF88]/20 text-[#00FF88] border border-[#00FF88]/60',
        line: 'border-l-[#00FF88]',
      };
    case 'LOSS':
      return {
        badge: 'bg-[#FF2D55]/20 text-[#FF2D55] border border-[#FF2D55]/60',
        line: 'border-l-[#FF2D55]',
      };
    case 'OPEN':
      return {
        badge: 'bg-transparent text-[#00E5FF] border border-[#00E5FF]/80',
        line: 'border-l-[#00E5FF]',
      };
    default:
      return {
        badge: 'bg-[#8BA8C4]/15 text-[#8BA8C4] border border-[#8BA8C4]/40',
        line: 'border-l-[#8BA8C4]/40',
      };
  }
}

function deepMergeDashboard(prev: DashboardState, incoming: Partial<DashboardState>): DashboardState {
  return {
    ...prev,
    ...incoming,
    position: { ...prev.position, ...(incoming.position ?? {}) },
    daily: { ...prev.daily, ...(incoming.daily ?? {}) },
    risk: { ...prev.risk, ...(incoming.risk ?? {}) },
    signal: { ...prev.signal, ...(incoming.signal ?? {}) },
    ai: { ...prev.ai, ...(incoming.ai ?? {}) },
    market: { ...prev.market, ...(incoming.market ?? {}) },
    pnlSeries: incoming.pnlSeries ?? prev.pnlSeries,
    tradeLog: incoming.tradeLog ?? prev.tradeLog,
    systemLogs: incoming.systemLogs ?? prev.systemLogs,
  };
}

function SlotValue({ value, className = '' }: { value: string | number; className?: string }) {
  const shown = typeof value === 'number' ? `${value}` : value;

  return (
    <span className={`inline-flex h-[1.1em] overflow-hidden leading-none ${className}`}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={shown}
          initial={{ y: '-105%', opacity: 0 }}
          animate={{ y: '0%', opacity: 1 }}
          exit={{ y: '105%', opacity: 0 }}
          transition={{ duration: 0.17, ease: 'easeOut' }}
          className="block tabular-nums"
        >
          {shown}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

function BlinkCursor() {
  return (
    <motion.span
      className="ml-0.5 inline-block text-[#00E5FF]"
      animate={{ opacity: [1, 0, 1] }}
      transition={{ duration: 0.7, repeat: Infinity, ease: 'linear' }}
    >
      _
    </motion.span>
  );
}

function HudPanel({
  title,
  right,
  className,
  children,
}: {
  title: ReactNode;
  right?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`${PANEL_CLASS} ${className ?? ''} flex min-h-0 flex-col`}>
      <div className="pointer-events-none absolute left-0 top-0 h-6 w-6 border-l border-t border-[#00E5FF]" />
      <div className="pointer-events-none absolute left-0 top-0 h-[2px] w-8 bg-[#00E5FF]/90 shadow-[0_0_10px_rgba(0,229,255,0.95)]" />
      <div className="pointer-events-none absolute left-0 top-0 h-8 w-[2px] bg-[#00E5FF]/90 shadow-[0_0_10px_rgba(0,229,255,0.95)]" />

      <header className="mb-2 flex items-center justify-between gap-2 border-b border-[#0D2137] pb-2">
        <h3 className="font-['Orbitron'] text-xs uppercase tracking-[0.24em] text-[#E0F4FF]">{title}</h3>
        {right}
      </header>

      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}

function StatusChip({
  label,
  color,
  pulse,
}: {
  label: ReactNode;
  color: string;
  pulse?: boolean;
}) {
  return (
    <div
      className="flex h-8 items-center gap-2 border border-[#0D2137] bg-[#070D14] px-3 text-[10px] uppercase tracking-[0.18em] text-[#E0F4FF]"
      style={{ boxShadow: `0 0 8px ${color}33` }}
    >
      <motion.span
        className="h-2 w-2 rounded-none"
        style={{ backgroundColor: color, boxShadow: `0 0 8px ${color}` }}
        animate={pulse ? { opacity: [1, 0.25, 1] } : { opacity: 1 }}
        transition={pulse ? { duration: 0.8, repeat: Infinity } : undefined}
      />
      <span className="text-[#8BA8C4]">{label}</span>
    </div>
  );
}

function ArcGauge({ value }: { value: number }) {
  const safe = Math.max(0, Math.min(100, value));
  const radius = 28;
  const circumference = Math.PI * radius;
  const strokeDashoffset = circumference - (safe / 100) * circumference;

  return (
    <div className="relative h-16 w-24">
      <svg viewBox="0 0 100 60" className="h-full w-full">
        <path d="M10 50 A40 40 0 0 1 90 50" fill="none" stroke="#0D2137" strokeWidth="8" />
        <path
          d="M10 50 A40 40 0 0 1 90 50"
          fill="none"
          stroke={COLORS.cyan}
          strokeWidth="8"
          strokeLinecap="square"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          style={{ filter: 'drop-shadow(0 0 6px #00E5FF)' }}
        />
      </svg>
      <div className="absolute inset-x-0 bottom-0 text-center font-['JetBrains_Mono'] text-xs text-[#E0F4FF]">{safe.toFixed(0)}%</div>
    </div>
  );
}

function RingGauge({
  value,
  max,
  color,
  size = 64,
}: {
  value: number;
  max: number;
  color: string;
  size?: number;
}) {
  const safe = Math.max(0, Math.min(max, value));
  const radius = size / 2 - 6;
  const circumference = 2 * Math.PI * radius;
  const progress = max <= 0 ? 0 : safe / max;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={radius} stroke="#0D2137" strokeWidth={4} fill="none" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        stroke={color}
        strokeWidth={4}
        fill="none"
        strokeLinecap="square"
        strokeDasharray={circumference}
        strokeDashoffset={circumference * (1 - progress)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ filter: `drop-shadow(0 0 5px ${color})` }}
      />
    </svg>
  );
}

function Marquee({ logs }: { logs: string[] }) {
  const message = [...logs, ...logs].join('    |    ');

  return (
    <div className="relative h-8 w-full overflow-hidden border border-[#0D2137] bg-[#070D14]">
      <motion.div
        className="absolute left-0 top-1/2 -translate-y-1/2 whitespace-nowrap font-['JetBrains_Mono'] text-[11px] text-[#00E5FF]/70"
        animate={{ x: ['0%', '-50%'] }}
        transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
      >
        {message}
      </motion.div>
    </div>
  );
}

function MobileCollapse({
  title,
  defaultOpen,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen} className="border border-[#0D2137] bg-[#050A0F]">
      <summary className="cursor-pointer px-3 py-2 font-['Orbitron'] text-[11px] uppercase tracking-[0.18em] text-[#E0F4FF]">
        {title}
      </summary>
      <div className="p-2">{children}</div>
    </details>
  );
}

export function Dashboard({ onLogout, onNavigate }: DashboardProps) {
  const [state, setState] = useState<DashboardState>(MOCK_DASHBOARD);
  const [utcNow, setUtcNow] = useState<Date>(new Date());
  const [lastTick, setLastTick] = useState<Date>(new Date());
  const [lastTickFlash, setLastTickFlash] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [showKillModal, setShowKillModal] = useState(false);
  const [killFlash, setKillFlash] = useState(false);
  const [resumeArmed, setResumeArmed] = useState(false);
  const [tabletTab, setTabletTab] = useState<TabletTab>('SYSTEM');
  const [showCrossoverOverlay, setShowCrossoverOverlay] = useState(false);
  const [copiedSlug, setCopiedSlug] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const noticeIdRef = useRef(0);
  const previousSignalRef = useRef<SignalResult | null>(null);

  const pushNotice = useCallback((item: Omit<NotificationItem, 'id'>) => {
    const id = ++noticeIdRef.current;
    setNotifications((prev) => [{ id, ...item }, ...prev].slice(0, 4));
    window.setTimeout(() => {
      setNotifications((prev) => prev.filter((notice) => notice.id !== id));
    }, 4800);
  }, []);

  const appendLog = useCallback((line: string) => {
    setState((prev) => ({
      ...prev,
      systemLogs: [line, ...prev.systemLogs].slice(0, 5),
    }));
  }, []);

  const totalPnl = useMemo(() => state.pnlSeries[state.pnlSeries.length - 1]?.pnl ?? 0, [state.pnlSeries]);

  const candleProgress = useMemo(() => {
    const elapsed = 3600 - state.market.remainingSeconds;
    return Math.max(0, Math.min(100, (elapsed / 3600) * 100));
  }, [state.market.remainingSeconds]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setUtcNow(new Date());
      setState((prev) => ({
        ...prev,
        position: {
          ...prev.position,
          holdSeconds: prev.position.open ? prev.position.holdSeconds + 1 : prev.position.holdSeconds,
        },
        risk: {
          ...prev.risk,
          cooldownSeconds: Math.max(0, prev.risk.cooldownSeconds - 1),
        },
        market: {
          ...prev.market,
          remainingSeconds: Math.max(0, prev.market.remainingSeconds - 1),
        },
      }));
    }, 1000);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setLastTick(new Date());
      setLastTickFlash(true);
      window.setTimeout(() => setLastTickFlash(false), 650);
    }, 60_000);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const pricePulse = [0.56, 0.559, 0.561, 0.562, 0.558, 0.56];
    let idx = 0;

    const timer = window.setInterval(() => {
      idx = (idx + 1) % pricePulse.length;
      const nextPrice = pricePulse[idx];

      setState((prev) => ({
        ...prev,
        position: {
          ...prev.position,
          currentPrice: nextPrice,
          unrealizedPnl: Number(((nextPrice - prev.position.entryPrice) * 19.25).toFixed(2)),
        },
      }));
    }, 4200);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    let reconnectTimer = 0;

    const connect = () => {
      if (!active) return;

      const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const socket = new WebSocket(`${wsProtocol}://${window.location.host}/ws`);
      wsRef.current = socket;

      socket.onopen = () => {
        setWsConnected(true);
      };

      socket.onmessage = (event) => {
        try {
          const incoming = JSON.parse(event.data) as Partial<DashboardState>;
          setState((prev) => deepMergeDashboard(prev, incoming));
        } catch {
          appendLog(`${formatUtcClock(new Date())} Invalid WS payload ignored`);
        }
      };

      socket.onerror = () => {
        socket.close();
      };

      socket.onclose = () => {
        setWsConnected(false);
        reconnectTimer = window.setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      active = false;
      window.clearTimeout(reconnectTimer);
      wsRef.current?.close();
    };
  }, [appendLog]);

  useEffect(() => {
    if (wsConnected) return;

    const poll = async () => {
      try {
        const response = await fetch('/api/status');
        if (!response.ok) return;
        const data = (await response.json()) as Partial<DashboardState>;
        setState((prev) => deepMergeDashboard(prev, data));
      } catch {
        // fallback remains on mock data intentionally
      }
    };

    poll();
    const timer = window.setInterval(poll, 5000);
    return () => window.clearInterval(timer);
  }, [wsConnected]);

  useEffect(() => {
    const previousSignal = previousSignalRef.current;
    previousSignalRef.current = state.signal.result;

    if (state.signal.result !== 'NONE' && previousSignal !== state.signal.result) {
      setShowCrossoverOverlay(true);
      const timer = window.setTimeout(() => setShowCrossoverOverlay(false), 3000);
      return () => window.clearTimeout(timer);
    }
  }, [state.signal.result]);

  useEffect(() => {
    if (state.killSwitch !== 'TRIPPED') return;

    setKillFlash(true);
    appendLog(`${formatUtcClock(new Date())} ⚠ KILL SWITCH ACTIVE — ALL TRADING HALTED`);

    const timer = window.setTimeout(() => setKillFlash(false), 2100);
    return () => window.clearTimeout(timer);
  }, [appendLog, state.killSwitch]);

  const handleTripKillSwitch = () => {
    setState((prev) => ({ ...prev, killSwitch: 'TRIPPED' }));
    setShowKillModal(false);
    pushNotice({
      type: 'loss',
      message: '⚠ KILL SWITCH TRIPPED',
      detail: 'All trading routes are now halted',
    });
  };

  const handleResumeKillSwitch = () => {
    if (!resumeArmed) {
      setResumeArmed(true);
      window.setTimeout(() => setResumeArmed(false), 1800);
      return;
    }

    setState((prev) => ({ ...prev, killSwitch: 'HEALTHY' }));
    setResumeArmed(false);
    appendLog(`${formatUtcClock(new Date())} Kill switch resumed by operator`);
  };

  const copySlug = async () => {
    try {
      await navigator.clipboard.writeText(state.market.slug);
      setCopiedSlug(true);
      window.setTimeout(() => setCopiedSlug(false), 1300);
    } catch {
      setCopiedSlug(false);
    }
  };

  const decisionColor = state.ai.decision === 'PROCEED' ? COLORS.green : COLORS.red;
  const signalColor =
    state.signal.result === 'LONG' ? COLORS.cyan : state.signal.result === 'SHORT' ? COLORS.red : COLORS.text;

  const systemStatusPanels = (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <HudPanel
        title="OPEN POSITIONS"
        right={
          <div className="flex items-center gap-1">
            <span className="text-[9px] uppercase tracking-[0.16em] text-[#8BA8C4]">RADAR</span>
            <motion.div className="relative h-4 w-4 border border-[#0D2137]" animate={{ rotate: 360 }} transition={{ duration: 2.4, repeat: Infinity, ease: 'linear' }}>
              <span className="absolute left-1/2 top-0 h-1/2 w-[1px] -translate-x-1/2 bg-[#00E5FF] shadow-[0_0_6px_#00E5FF]" />
            </motion.div>
          </div>
        }
        className="min-h-[230px] flex-1"
      >
        {state.position.open ? (
          <div className="flex h-full flex-col gap-2 font-['JetBrains_Mono'] text-xs text-[#8BA8C4]">
            <div className="border border-[#0D2137] bg-[#050A0F] p-2">
              <p className="font-['Orbitron'] text-2xl tracking-[0.14em] text-[#E0F4FF]" style={{ textShadow: '0 0 10px rgba(0,229,255,0.75)' }}>
                {state.position.token}
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="border border-[#0D2137] bg-[#050A0F] p-2">
                <p className="text-[10px] uppercase tracking-[0.16em]">ENTRY</p>
                <p className="mt-1 text-base text-[#E0F4FF]">
                  <SlotValue value={formatPrice(state.position.entryPrice)} />
                </p>
              </div>
              <div className="border border-[#0D2137] bg-[#050A0F] p-2">
                <p className="text-[10px] uppercase tracking-[0.16em]">CURRENT</p>
                <p className="mt-1 text-base" style={{ color: state.position.currentPrice >= state.position.entryPrice ? COLORS.green : COLORS.red }}>
                  <SlotValue value={formatPrice(state.position.currentPrice)} />
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="border border-[#0D2137] bg-[#050A0F] p-2">
                <p className="text-[10px] uppercase tracking-[0.16em]">UNREALIZED P&L</p>
                <p className="mt-1 text-base" style={{ color: state.position.unrealizedPnl >= 0 ? COLORS.green : COLORS.red }}>
                  <SlotValue value={formatDollar(state.position.unrealizedPnl)} />
                </p>
              </div>
              <div className="border border-[#0D2137] bg-[#050A0F] p-2">
                <p className="text-[10px] uppercase tracking-[0.16em]">HOLD TIME</p>
                <p className="mt-1 text-base text-[#E0F4FF]">
                  <SlotValue value={secondsToClock(state.position.holdSeconds)} />
                </p>
              </div>
            </div>

            <div className="flex items-center justify-between gap-2 border border-[#0D2137] bg-[#050A0F] px-2 py-1.5">
              <span className="text-[10px] uppercase tracking-[0.16em]">EXIT MODE</span>
              <span className="border border-[#00E5FF]/60 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-[#00E5FF] shadow-[0_0_8px_rgba(0,229,255,0.5)]">
                {state.position.exitMode}
              </span>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-[10px] uppercase tracking-[0.16em]">
                <span>CANDLE ELAPSED</span>
                <span>{Math.round(candleProgress)}%</span>
              </div>
              <div className="h-2 border border-[#0D2137] bg-[#050A0F]">
                <motion.div
                  className="h-full bg-[#00E5FF] shadow-[0_0_10px_rgba(0,229,255,0.85)]"
                  animate={{ width: `${candleProgress}%` }}
                  transition={{ duration: 0.4, ease: 'easeOut' }}
                />
              </div>
            </div>
          </div>
        ) : (
          <div className="relative flex h-full items-center justify-center border border-[#0D2137] bg-[#050A0F] text-[#8BA8C4]">
            <motion.div
              className="pointer-events-none absolute h-20 w-20 border border-[#0D2137]"
              animate={{ rotate: 360 }}
              transition={{ duration: 6, repeat: Infinity, ease: 'linear' }}
            />
            <span className="font-['Orbitron'] text-xs tracking-[0.2em]">NO ACTIVE POSITION</span>
          </div>
        )}
      </HudPanel>

      <HudPanel title="TODAY'S PERFORMANCE" className="min-h-[200px] flex-1">
        <div className="grid h-full grid-cols-2 gap-2 text-xs text-[#8BA8C4]">
          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <p className="uppercase tracking-[0.16em]">TRADES</p>
            <p className="mt-2 font-['JetBrains_Mono'] text-xl text-[#E0F4FF]">
              <SlotValue value={`${state.daily.tradesUsed} / ${state.daily.tradeLimit}`} />
            </p>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <p className="uppercase tracking-[0.16em]">WIN RATE</p>
            <div className="mt-1 flex justify-center">
              <ArcGauge value={state.daily.winRate} />
            </div>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <p className="uppercase tracking-[0.16em]">NET P&L</p>
            <p className="mt-2 font-['JetBrains_Mono'] text-xl" style={{ color: state.daily.netPnl >= 0 ? COLORS.green : COLORS.red }}>
              <SlotValue value={formatDollar(state.daily.netPnl)} />
            </p>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <p className="uppercase tracking-[0.16em]">DAILY LOSS USED</p>
            <p className="mt-1 font-['JetBrains_Mono'] text-sm text-[#E0F4FF]">
              <SlotValue value={`$${state.daily.dailyLossUsed.toFixed(2)} / $${state.daily.dailyLossLimit.toFixed(2)}`} />
            </p>
            <div className="mt-2 h-2 border border-[#0D2137] bg-[#020408]">
              <div
                className="h-full bg-[#FF9500] shadow-[0_0_10px_rgba(255,149,0,0.65)]"
                style={{ width: `${Math.min(100, (state.daily.dailyLossUsed / state.daily.dailyLossLimit) * 100)}%` }}
              />
            </div>
          </div>
        </div>
      </HudPanel>

      <HudPanel title="RISK ENGINE" className="min-h-[205px] flex-1">
        <div className="flex h-full flex-col gap-2 text-xs text-[#8BA8C4]">
          <div className="flex items-center gap-3 border border-[#0D2137] bg-[#050A0F] p-2">
            <RingGauge value={state.risk.cooldownSeconds} max={5 * 60} color={COLORS.cyan} />
            <div>
              <p className="uppercase tracking-[0.16em]">COOLDOWN</p>
              <p className="mt-1 font-['JetBrains_Mono'] text-lg text-[#E0F4FF]">
                <SlotValue value={secondsToClock(state.risk.cooldownSeconds)} />
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="border border-[#0D2137] bg-[#050A0F] p-2">
              <p className="uppercase tracking-[0.16em]">MAX TRADE SIZE</p>
              <p className="mt-1 font-['JetBrains_Mono'] text-base text-[#E0F4FF]">
                <SlotValue value={`$${state.risk.maxTradeSize.toFixed(2)}`} />
              </p>
            </div>
            <div className="border border-[#0D2137] bg-[#050A0F] p-2">
              <p className="uppercase tracking-[0.16em]">OPEN SLOTS</p>
              <p className="mt-1 font-['JetBrains_Mono'] text-base text-[#E0F4FF]">
                <SlotValue value={`${state.risk.openSlots} / ${state.risk.maxSlots} USED`} />
              </p>
            </div>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <div className="flex items-center justify-between uppercase tracking-[0.16em]">
              <span>Daily loss remaining</span>
              <span className="font-['JetBrains_Mono'] text-[#E0F4FF]">${state.risk.dailyLossRemaining.toFixed(2)}</span>
            </div>
            <div className="mt-2 h-2 border border-[#0D2137] bg-[#020408]">
              <div
                className="h-full"
                style={{
                  width: `${Math.min(100, (state.risk.dailyLossRemaining / state.risk.dailyLossCap) * 100)}%`,
                  backgroundColor:
                    state.risk.dailyLossRemaining / state.risk.dailyLossCap < 0.2 ? COLORS.red : COLORS.green,
                  boxShadow:
                    state.risk.dailyLossRemaining / state.risk.dailyLossCap < 0.2
                      ? '0 0 8px rgba(255,45,85,0.75)'
                      : '0 0 8px rgba(0,255,136,0.65)',
                }}
              />
            </div>
          </div>

          <button
            onClick={() => setShowKillModal(true)}
            className="mt-auto border border-[#FF2D55] bg-transparent px-3 py-2 font-['Orbitron'] text-[11px] uppercase tracking-[0.18em] text-[#FF2D55] shadow-[0_0_10px_rgba(255,45,85,0.5)] hover:bg-[#FF2D55]/10"
          >
            KILL SWITCH TRIP
          </button>
        </div>
      </HudPanel>
    </div>
  );

  const signalLabel =
    state.signal.rsi < 30 ? 'OVERSOLD ZONE' : state.signal.rsi > 70 ? 'OVERBOUGHT' : 'NEUTRAL';

  const mainRadarPanels = (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <HudPanel
        title="CUMULATIVE P&L — 7D"
        className="basis-[40%] min-h-[220px]"
        right={
          <span className="border border-[#0D2137] bg-[#050A0F] px-2 py-1 font-['JetBrains_Mono'] text-[11px] text-[#00FF88] shadow-[0_0_8px_rgba(0,255,136,0.4)]">
            {formatDollar(totalPnl)} NET
          </span>
        }
      >
        <div className="h-[290px] w-full min-h-0 xl:h-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={state.pnlSeries} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
            <defs>
              <linearGradient id="pnlFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={totalPnl >= 0 ? COLORS.cyan : COLORS.red} stopOpacity={0.4} />
                <stop offset="100%" stopColor={totalPnl >= 0 ? COLORS.cyan : COLORS.red} stopOpacity={0.02} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke="#0D2137" strokeDasharray="2 4" />
            <XAxis dataKey="time" tick={{ fill: COLORS.text, fontSize: 10 }} tickLine={false} axisLine={false} />
            <YAxis
              tick={{ fill: COLORS.text, fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(value: number) => `$${value.toFixed(0)}`}
            />

            <Tooltip
              cursor={{ stroke: COLORS.cyan, strokeDasharray: '4 4' }}
              contentStyle={{
                background: '#050A0F',
                border: `1px solid ${COLORS.border}`,
                borderRadius: 0,
                color: COLORS.bright,
                boxShadow: '0 0 10px rgba(0,229,255,0.35)',
              }}
              formatter={(value: number) => [`$${value.toFixed(2)} USDC`, 'P&L']}
              labelStyle={{ color: COLORS.text }}
            />

            <ReferenceLine y={0} stroke={COLORS.text} strokeDasharray="3 4" />
              <Area
                type="monotone"
                dataKey="pnl"
                stroke={totalPnl >= 0 ? COLORS.cyan : COLORS.red}
                strokeWidth={2}
                fill="url(#pnlFill)"
                isAnimationActive={false}
                dot={(props) => {
                const point = props.payload as PnlPoint;
                if (!point.trade) return <></>;
                return (
                  <circle
                    cx={props.cx}
                    cy={props.cy}
                    r={3.5}
                    fill={COLORS.amber}
                    stroke={COLORS.bright}
                    strokeWidth={1}
                    style={{ filter: 'drop-shadow(0 0 4px rgba(255,149,0,0.9))' }}
                  />
                );
              }}
                activeDot={{ r: 5, stroke: COLORS.bright, strokeWidth: 1 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </HudPanel>

      <HudPanel
        title={
          <span>
            SIGNAL ENGINE — LIVE
            <BlinkCursor />
          </span>
        }
        className="relative basis-[35%] min-h-[220px]"
      >
        <div className="grid h-full grid-cols-1 gap-2 lg:grid-cols-2">
          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <div className="mb-2 flex items-center justify-between">
              <p className="font-['Orbitron'] text-[11px] uppercase tracking-[0.18em] text-[#E0F4FF]">RSI (14)</p>
              <p className="font-['JetBrains_Mono'] text-2xl text-[#00E5FF]" style={{ textShadow: '0 0 8px rgba(0,229,255,0.8)' }}>
                <SlotValue value={state.signal.rsi.toFixed(1)} />
              </p>
            </div>

            <div className="flex gap-3">
              <div className="relative h-36 w-8 border border-[#0D2137] bg-[#020408]">
                <div className="absolute inset-x-0 top-0 h-[30%] bg-[#FF2D55]/25" />
                <div className="absolute inset-x-0 top-[30%] h-[40%] bg-[#8BA8C4]/15" />
                <div className="absolute inset-x-0 top-[70%] h-[30%] bg-[#FF2D55]/25" />
                <motion.div
                  className="absolute left-0 h-[2px] w-full bg-[#00E5FF] shadow-[0_0_8px_rgba(0,229,255,0.85)]"
                  animate={{ top: `${100 - state.signal.rsi}%` }}
                  transition={{ duration: 0.25 }}
                />
              </div>

              <div className="flex-1">
                <p className="mb-2 border border-[#0D2137] bg-[#020408] px-2 py-1 font-['Orbitron'] text-[10px] uppercase tracking-[0.16em] text-[#8BA8C4]">
                  {signalLabel}
                </p>
                <div className="h-[95px] border border-[#0D2137] bg-[#020408] p-1">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={state.signal.rsiSeries.map((value, index) => ({ i: index, value }))}>
                      <Line
                        type="monotone"
                        dataKey="value"
                        stroke={COLORS.cyan}
                        dot={false}
                        strokeWidth={2}
                        isAnimationActive={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <div className="mb-2 flex items-center justify-between font-['JetBrains_Mono'] text-xs">
              <p className="font-['Orbitron'] text-[11px] uppercase tracking-[0.18em] text-[#E0F4FF]">SLOW STOCH (14,3,3)</p>
              <p className="text-[#8BA8C4]">
                %K <span className="text-[#00FF88]">{state.signal.stochK.toFixed(1)}</span> · %D{' '}
                <span className="text-[#FF9500]">{state.signal.stochD.toFixed(1)}</span>
              </p>
            </div>

            <div className="h-[120px] border border-[#0D2137] bg-[#020408] p-1">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={state.signal.stochKSeries.map((value, index) => ({
                    i: index,
                    k: value,
                    d: state.signal.stochDSeries[index] ?? state.signal.stochD,
                  }))}
                >
                  <Line
                    type="monotone"
                    dataKey="k"
                    stroke={COLORS.green}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="d"
                    stroke={COLORS.amber}
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            <motion.p
              className="mt-2 border border-[#0D2137] bg-[#020408] px-2 py-1 font-['Orbitron'] text-[10px] uppercase tracking-[0.18em]"
              style={{ color: state.signal.stochK >= state.signal.stochD ? COLORS.green : COLORS.red }}
              animate={state.signal.stochK >= state.signal.stochD ? { opacity: [1, 0.6, 1] } : { opacity: [1, 0.6, 1] }}
              transition={{ duration: 0.9, repeat: Infinity }}
            >
              {state.signal.stochK >= state.signal.stochD ? '▲ K CROSSES D' : '▼ K CROSSES D'}
            </motion.p>
          </div>
        </div>

        <div className="mt-2">
          <motion.div
            className="border border-[#0D2137] bg-[#020408] px-3 py-2 text-center font-['Orbitron'] text-sm uppercase tracking-[0.22em]"
            style={{ color: signalColor, boxShadow: `0 0 12px ${signalColor}55 inset` }}
            animate={{ opacity: [1, 0.82, 1] }}
            transition={{ duration: 1.2, repeat: Infinity }}
          >
            {state.signal.result === 'LONG' && '● LONG SIGNAL — BET UP'}
            {state.signal.result === 'SHORT' && '● SHORT SIGNAL — BET DOWN'}
            {state.signal.result === 'NONE' && '○ NO SIGNAL'}
          </motion.div>
        </div>

        <AnimatePresence>
          {showCrossoverOverlay && (
            <motion.div
              className="absolute inset-0 z-20 flex items-center justify-center border border-[#00E5FF] bg-[#020408]/90"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <motion.span
                className="font-['Orbitron'] text-xl uppercase tracking-[0.32em] text-[#00E5FF]"
                animate={{ opacity: [1, 0.35, 1] }}
                transition={{ duration: 0.35, repeat: Infinity }}
                style={{ textShadow: '0 0 12px rgba(0,229,255,0.9)' }}
              >
                CROSSOVER DETECTED
              </motion.span>
            </motion.div>
          )}
        </AnimatePresence>
      </HudPanel>

      <HudPanel
        title="TRADE LOG"
        className="basis-[25%] min-h-[180px]"
        right={
          <button className="font-['JetBrains_Mono'] text-[11px] uppercase tracking-[0.16em] text-[#00E5FF] hover:text-[#E0F4FF]">
            VIEW ALL
          </button>
        }
      >
        <div className="h-full overflow-auto border border-[#0D2137] bg-[#050A0F]">
          <table className="w-full min-w-[900px] border-collapse text-[10px] uppercase tracking-[0.12em] text-[#8BA8C4]">
            <thead className="sticky top-0 bg-[#020408] text-[#E0F4FF]">
              <tr>
                <th className="px-2 py-1 text-left">Time</th>
                <th className="px-2 py-1 text-left">Direction</th>
                <th className="px-2 py-1 text-left">Entry</th>
                <th className="px-2 py-1 text-left">Exit</th>
                <th className="px-2 py-1 text-left">Size</th>
                <th className="px-2 py-1 text-left">P&L</th>
                <th className="px-2 py-1 text-left">Exit Reason</th>
                <th className="px-2 py-1 text-left">Mode</th>
              </tr>
            </thead>
            <tbody>
              {state.tradeLog.slice(0, 8).map((trade, index) => {
                const styles = tradeStatusStyles(trade.status);
                return (
                  <tr
                    key={`${trade.time}-${index}`}
                    className={`border-l-2 ${styles.line} ${index % 2 === 0 ? 'bg-[#070D14]' : 'bg-[#050A0F]'}`}
                  >
                    <td className="px-2 py-1 font-['JetBrains_Mono']">{trade.time}</td>
                    <td className="px-2 py-1">{trade.direction}</td>
                    <td className="px-2 py-1 font-['JetBrains_Mono']">{formatPrice(trade.entry)}</td>
                    <td className="px-2 py-1 font-['JetBrains_Mono']">{trade.exit === null ? '—' : formatPrice(trade.exit)}</td>
                    <td className="px-2 py-1 font-['JetBrains_Mono']">${trade.size.toFixed(2)}</td>
                    <td
                      className="px-2 py-1 font-['JetBrains_Mono']"
                      style={{
                        color:
                          trade.pnl === null
                            ? COLORS.text
                            : trade.pnl > 0
                              ? COLORS.green
                              : trade.pnl < 0
                                ? COLORS.red
                                : COLORS.text,
                      }}
                    >
                      {trade.pnl === null ? '—' : formatDollar(trade.pnl).replace('+', '')}
                    </td>
                    <td className="px-2 py-1">{trade.exitReason}</td>
                    <td className="px-2 py-1">
                      <span className={`inline-block px-1.5 py-0.5 ${styles.badge}`}>{trade.status}</span>
                      <span className="ml-1 text-[#8BA8C4]">{trade.mode}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </HudPanel>
    </div>
  );

  const aiPanels = (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <HudPanel
        title="AI DECISION ENGINE"
        className="min-h-[265px] flex-1"
        right={<span className="text-[10px] text-[#8BA8C4]">◉ Neural Core</span>}
      >
        <div className="flex h-full flex-col gap-2 text-xs text-[#8BA8C4]">
          <div className="flex items-center justify-between border border-[#0D2137] bg-[#050A0F] p-2">
            <p className="font-['Orbitron'] text-[10px] uppercase tracking-[0.18em] text-[#E0F4FF]">Status</p>
            <button
              onClick={() => setState((prev) => ({ ...prev, ai: { ...prev.ai, enabled: !prev.ai.enabled } }))}
              className="flex items-center gap-2 border border-[#0D2137] bg-[#020408] px-2 py-1"
            >
              <span
                className="h-2 w-6 border border-[#0D2137]"
                style={{
                  background: state.ai.enabled ? COLORS.green : COLORS.red,
                  boxShadow: state.ai.enabled
                    ? '0 0 8px rgba(0,255,136,0.7)'
                    : '0 0 8px rgba(255,45,85,0.75)',
                }}
              />
              <span className="font-['Orbitron'] text-[10px] uppercase tracking-[0.18em]">
                {state.ai.enabled ? 'ENABLED' : 'DISABLED'}
              </span>
            </button>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2">
            <div className="mb-2 flex items-center justify-between">
              <p className="font-['Orbitron'] text-[10px] uppercase tracking-[0.16em]">Last Decision</p>
              <p className="font-['Orbitron'] text-lg tracking-[0.2em]" style={{ color: decisionColor }}>
                {state.ai.decision}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <ArcGauge value={state.ai.probability * 100} />
              <div className="space-y-1 font-['JetBrains_Mono'] text-[11px]">
                <p>
                  Market price: <span className="text-[#E0F4FF]">{(state.ai.marketPrice * 100).toFixed(1)}¢</span>
                </p>
                <p>
                  Edge: <span className="text-[#00FF88]">+{(state.ai.edge * 100).toFixed(1)}¢</span>
                </p>
                <p>
                  Position factor: <span className="text-[#E0F4FF]">{state.ai.positionFactor.toFixed(2)}x</span>
                </p>
                <p>
                  Latency: <span className="text-[#E0F4FF]">{state.ai.latencySeconds.toFixed(2)}s</span>
                </p>
              </div>
            </div>

            <div className="mt-2">
              <div className="mb-1 flex justify-between text-[10px] uppercase tracking-[0.14em]">
                <span>Confidence</span>
                <span className="font-['JetBrains_Mono'] text-[#E0F4FF]">{state.ai.confidence}/100</span>
              </div>
              <div className="h-2 border border-[#0D2137] bg-[#020408]">
                <div
                  className="h-full bg-[#00E5FF] shadow-[0_0_10px_rgba(0,229,255,0.75)]"
                  style={{ width: `${state.ai.confidence}%` }}
                />
              </div>
            </div>

            <div className="mt-2 flex flex-wrap gap-1">
              {state.ai.warningFlags.map((flag) => (
                <span
                  key={flag}
                  className="border border-[#FF9500]/80 bg-[#FF9500]/15 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-[#FF9500]"
                >
                  {flag}
                </span>
              ))}
            </div>
          </div>

          <div className="min-h-[72px] flex-1 overflow-auto border border-[#0D2137] bg-[#020408] p-2 font-['JetBrains_Mono'] text-[11px] text-[#8BA8C4]">
            {state.ai.reasoning}
          </div>
        </div>
      </HudPanel>

      <HudPanel title="AI PERFORMANCE" className="min-h-[180px] flex-1">
        <div className="grid h-full grid-cols-2 gap-2 text-xs text-[#8BA8C4]">
          <div className="space-y-1 border border-[#0D2137] bg-[#050A0F] p-2 font-['JetBrains_Mono']">
            <p>
              Total decisions: <span className="text-[#E0F4FF]">{state.ai.totalDecisions}</span>
            </p>
            <p>
              Avg latency: <span className="text-[#E0F4FF]">{state.ai.avgLatency.toFixed(1)}s</span>
            </p>
            <p>
              AI accuracy: <span className="text-[#00FF88]">{state.ai.accuracy}%</span>
            </p>
            <p style={{ color: state.ai.consecutiveFailures > 3 ? COLORS.red : COLORS.text }}>
              Consecutive failures: {state.ai.consecutiveFailures}
            </p>
          </div>

          <div className="h-[140px] border border-[#0D2137] bg-[#050A0F] p-1">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={[
                    { name: 'Proceed', value: 100 - state.ai.vetoRate },
                    { name: 'Vetoed', value: state.ai.vetoRate },
                  ]}
                  dataKey="value"
                  innerRadius={26}
                  outerRadius={42}
                  stroke="none"
                  isAnimationActive={false}
                >
                  <Cell fill={COLORS.green} />
                  <Cell fill={COLORS.red} />
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: '#050A0F',
                    border: `1px solid ${COLORS.border}`,
                    borderRadius: 0,
                    color: COLORS.bright,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <p className="-mt-1 text-center font-['JetBrains_Mono'] text-[11px] text-[#E0F4FF]">
              VETO RATE {state.ai.vetoRate}%
            </p>
          </div>
        </div>
      </HudPanel>

      <HudPanel title="MARKET CONTEXT" className="min-h-[200px] flex-1">
        <div className="flex h-full flex-col gap-2 text-xs text-[#8BA8C4]">
          <div className="flex items-center gap-2 border border-[#0D2137] bg-[#050A0F] p-2 font-['JetBrains_Mono']">
            <p className="flex-1 truncate">{state.market.slug}</p>
            <button
              onClick={copySlug}
              className="border border-[#0D2137] px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-[#00E5FF] hover:text-[#E0F4FF]"
            >
              {copiedSlug ? 'COPIED' : 'COPY'}
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="border border-[#0D2137] bg-[#050A0F] p-2">
              <p className="uppercase tracking-[0.14em]">Candle open</p>
              <p className="mt-1 font-['JetBrains_Mono'] text-[#E0F4FF]">{state.market.candleOpen}</p>
            </div>
            <div className="border border-[#0D2137] bg-[#050A0F] p-2">
              <p className="uppercase tracking-[0.14em]">Candle close</p>
              <p className="mt-1 font-['JetBrains_Mono'] text-[#E0F4FF]">{state.market.candleClose}</p>
            </div>
          </div>

          <div className="flex items-center gap-3 border border-[#0D2137] bg-[#050A0F] p-2">
            <RingGauge value={state.market.remainingSeconds} max={3600} color={COLORS.cyan} />
            <div>
              <p className="uppercase tracking-[0.16em]">Time remaining</p>
              <p className="mt-1 font-['JetBrains_Mono'] text-lg text-[#E0F4FF]">
                <SlotValue value={secondsToClock(state.market.remainingSeconds)} />
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="border border-[#0D2137] bg-[#050A0F] p-2 font-['JetBrains_Mono']">
              <p>Spread</p>
              <p style={{ color: state.market.spreadCents <= 3 ? COLORS.green : COLORS.red }}>{formatCents(state.market.spreadCents)}</p>
            </div>
            <div className="border border-[#0D2137] bg-[#050A0F] p-2 font-['JetBrains_Mono']">
              <p>UP / DOWN</p>
              <p className="text-[#E0F4FF]">
                {state.market.upPriceCents.toFixed(1)}¢ / {state.market.downPriceCents.toFixed(1)}¢
              </p>
            </div>
          </div>

          <div className="border border-[#0D2137] bg-[#050A0F] p-2 font-['JetBrains_Mono'] text-[11px] text-[#8BA8C4]">
            Resolution source: <span className="text-[#E0F4FF]">{state.market.resolutionSource}</span>
          </div>
        </div>
      </HudPanel>
    </div>
  );

  return (
    <div
      className="relative overflow-hidden bg-[#020408] text-[#E0F4FF]"
      style={{ fontFamily: 'Inter, sans-serif', height: '100vh' }}
    >
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Orbitron:wght@500;700;900&display=swap');`}</style>

      <div className="pointer-events-none absolute inset-0 opacity-20" style={{ backgroundImage: noiseTexture }} />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            'repeating-linear-gradient(to bottom, rgba(224,244,255,1) 0px, rgba(224,244,255,1) 2px, transparent 2px, transparent 4px)',
        }}
      />

      <AnimatePresence>
        {killFlash && (
          <motion.div
            className="pointer-events-none fixed inset-0 z-40 bg-[#FF2D55]"
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0.45, 0, 0.45, 0, 0.45, 0] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.8, ease: 'linear' }}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {state.killSwitch === 'TRIPPED' && (
          <motion.div
            className="fixed inset-x-0 top-0 z-50 flex h-12 items-center justify-between border-b border-[#FF2D55] bg-[#12040A] px-4"
            initial={{ y: -48 }}
            animate={{ y: 0 }}
            exit={{ y: -48 }}
          >
            <p className="font-['Orbitron'] text-xs uppercase tracking-[0.22em] text-[#FF2D55]">
              ⚠ KILL SWITCH ACTIVE — ALL TRADING HALTED
            </p>
            <button
              onClick={handleResumeKillSwitch}
              className="border border-[#FF2D55] px-3 py-1 font-['Orbitron'] text-[10px] uppercase tracking-[0.18em] text-[#FF2D55] hover:bg-[#FF2D55]/10"
            >
              {resumeArmed ? 'CLICK AGAIN TO CONFIRM' : 'RESUME'}
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative z-20 grid h-full min-h-0 grid-rows-[64px_minmax(0,1fr)_48px]">
        <header className="grid grid-cols-12 items-center border-b border-[#0D2137] px-3">
          <div className="col-span-12 flex items-center justify-between gap-2 lg:col-span-4">
            <motion.div
              className="flex items-center gap-2"
              animate={{ opacity: [1, 0.98, 1, 0.985, 1] }}
              transition={{ duration: 2.2, repeat: Infinity, ease: 'linear' }}
            >
              <motion.span
                className="font-['Orbitron'] text-2xl text-[#00E5FF]"
                animate={{ scale: [1, 1.08, 1] }}
                transition={{ duration: 1.4, repeat: Infinity }}
                style={{ textShadow: '0 0 10px rgba(0,229,255,0.95), 0 0 20px rgba(0,229,255,0.55)' }}
              >
                ∞
              </motion.span>
              <h1
                className="font-['Orbitron'] text-[15px] uppercase tracking-[0.26em] text-[#00E5FF]"
                style={{ textShadow: '0 0 10px rgba(0,229,255,0.95), 0 0 18px rgba(0,229,255,0.5)' }}
              >
                INFINITE GAINS
              </h1>
            </motion.div>
            <button
              onClick={onLogout}
              className="hidden border border-[#0D2137] px-2 py-1 font-['JetBrains_Mono'] text-[10px] uppercase tracking-[0.16em] text-[#8BA8C4] hover:text-[#E0F4FF] lg:block"
            >
              LOG OUT
            </button>
          </div>

          <div className="col-span-12 hidden justify-center lg:col-span-3 lg:flex">
            <div className="border border-[#0D2137] bg-[#070D14] px-3 py-1 font-['JetBrains_Mono'] text-sm text-[#E0F4FF] shadow-[0_0_8px_rgba(0,229,255,0.3)]">
              {formatUtcClock(utcNow)}
            </div>
          </div>

          <div className="col-span-12 flex items-center justify-end gap-2 lg:col-span-5">
            <StatusChip
              color={state.mode === 'LIVE' ? COLORS.green : COLORS.amber}
              label={state.mode === 'LIVE' ? '● LIVE MODE' : '● PAPER MODE'}
              pulse={state.mode === 'LIVE'}
            />

            <StatusChip
              color={state.killSwitch === 'TRIPPED' ? COLORS.red : COLORS.green}
              label={state.killSwitch === 'TRIPPED' ? '⚠ KILL SWITCH: TRIPPED' : '● KILL SWITCH: HEALTHY'}
              pulse={state.killSwitch === 'TRIPPED'}
            />

            <StatusChip
              color={wsConnected ? COLORS.green : COLORS.red}
              label={
                <span>
                  {wsConnected ? '● WS CONNECTED' : '● WS DISCONNECTED'}
                  <BlinkCursor />
                </span>
              }
              pulse
            />
          </div>
        </header>

        <main className="min-h-0 overflow-hidden border-y border-[#0D2137] p-2">
          <div className="hidden h-full min-h-0 grid-cols-12 gap-2 xl:grid">
            <aside className="col-span-3 min-h-0 overflow-auto">{systemStatusPanels}</aside>
            <section className="col-span-6 min-h-0 overflow-hidden">{mainRadarPanels}</section>
            <aside className="col-span-3 min-h-0 overflow-auto">{aiPanels}</aside>
          </div>

          <div className="hidden h-full min-h-0 flex-col gap-2 overflow-hidden md:flex xl:hidden">
            <div className="min-h-0 flex-[1.2] overflow-hidden">{mainRadarPanels}</div>

            <div className="flex gap-2">
              <button
                onClick={() => setTabletTab('SYSTEM')}
                className={`border px-3 py-1 font-['Orbitron'] text-[11px] uppercase tracking-[0.18em] ${
                  tabletTab === 'SYSTEM'
                    ? 'border-[#00E5FF] bg-[#00E5FF]/10 text-[#00E5FF]'
                    : 'border-[#0D2137] bg-[#050A0F] text-[#8BA8C4]'
                }`}
              >
                SYSTEM STATUS
              </button>
              <button
                onClick={() => setTabletTab('AI')}
                className={`border px-3 py-1 font-['Orbitron'] text-[11px] uppercase tracking-[0.18em] ${
                  tabletTab === 'AI'
                    ? 'border-[#00E5FF] bg-[#00E5FF]/10 text-[#00E5FF]'
                    : 'border-[#0D2137] bg-[#050A0F] text-[#8BA8C4]'
                }`}
              >
                AI BRAIN
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-auto">{tabletTab === 'SYSTEM' ? systemStatusPanels : aiPanels}</div>
          </div>

          <div className="h-full overflow-auto md:hidden">
            <div className="flex flex-col gap-2 pb-6">
              <MobileCollapse title="MAIN RADAR" defaultOpen>
                {mainRadarPanels}
              </MobileCollapse>
              <MobileCollapse title="SYSTEM STATUS">{systemStatusPanels}</MobileCollapse>
              <MobileCollapse title="AI BRAIN">{aiPanels}</MobileCollapse>
            </div>
          </div>
        </main>

        <footer className="grid grid-cols-12 items-center gap-2 px-3">
          <div
            className="col-span-12 border border-[#0D2137] bg-[#070D14] px-2 py-1 font-['JetBrains_Mono'] text-[11px] text-[#8BA8C4] md:col-span-3"
            style={{ boxShadow: lastTickFlash ? '0 0 10px rgba(0,229,255,0.65)' : undefined }}
          >
            LAST TICK: <span className="text-[#E0F4FF]">{formatUtcClock(lastTick)}</span>
          </div>

          <div className="col-span-12 md:col-span-6">
            <Marquee logs={state.systemLogs} />
          </div>

          <div className="col-span-12 flex items-center justify-end gap-2 md:col-span-3">
            <button
              onClick={() => onNavigate?.('financial')}
              className="border border-[#0D2137] bg-[#070D14] px-2 py-1 font-['JetBrains_Mono'] text-[10px] uppercase tracking-[0.16em] text-[#00E5FF] hover:text-[#E0F4FF]"
            >
              METRICS_PORT
            </button>
            <button
              onClick={() => onNavigate?.('erp')}
              className="border border-[#0D2137] bg-[#070D14] px-2 py-1 font-['JetBrains_Mono'] text-[10px] uppercase tracking-[0.16em] text-[#00E5FF] hover:text-[#E0F4FF]"
            >
              GRAFANA →
            </button>
          </div>
        </footer>
      </div>

      <AnimatePresence>
        {notifications.length > 0 && (
          <div className="pointer-events-none fixed right-3 top-20 z-[55] flex w-[340px] max-w-[92vw] flex-col gap-2">
            <AnimatePresence>
              {notifications.map((note) => {
                const tone =
                  note.type === 'win' ? COLORS.green : note.type === 'loss' ? COLORS.red : COLORS.cyan;
                return (
                  <motion.div
                    key={note.id}
                    initial={{ x: 30, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    exit={{ x: 40, opacity: 0 }}
                    className="border bg-[#050A0F] px-3 py-2"
                    style={{ borderColor: tone, boxShadow: `0 0 14px ${tone}55` }}
                  >
                    <p className="font-['Orbitron'] text-[11px] uppercase tracking-[0.18em]" style={{ color: tone }}>
                      {note.message}
                    </p>
                    <p className="mt-1 font-['JetBrains_Mono'] text-[10px] uppercase tracking-[0.16em] text-[#8BA8C4]">
                      {note.detail}
                    </p>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showKillModal && (
          <motion.div
            className="fixed inset-0 z-[60] flex items-center justify-center bg-[#020408]/90 p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-md border border-[#FF2D55] bg-[#070D14] p-4 shadow-[0_0_16px_rgba(255,45,85,0.55)]"
            >
              <h2 className="font-['Orbitron'] text-sm uppercase tracking-[0.2em] text-[#FF2D55]">Confirm Kill Switch Trip</h2>
              <p className="mt-2 font-['JetBrains_Mono'] text-xs text-[#8BA8C4]">
                This immediately halts all trading decisions, order creation, and strategy execution.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  onClick={() => setShowKillModal(false)}
                  className="border border-[#0D2137] px-3 py-1 font-['Orbitron'] text-[10px] uppercase tracking-[0.16em] text-[#8BA8C4]"
                >
                  CANCEL
                </button>
                <button
                  onClick={handleTripKillSwitch}
                  className="border border-[#FF2D55] px-3 py-1 font-['Orbitron'] text-[10px] uppercase tracking-[0.16em] text-[#FF2D55] shadow-[0_0_10px_rgba(255,45,85,0.45)]"
                >
                  TRIP NOW
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default Dashboard;
