import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { renderBody } from '../lib/format';
import type { AuthorBadge } from '../lib/types';

/* ------------------------------------------------------------------ icons */

const svg = (path: ReactNode, size = 16) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {path}
  </svg>
);

export const Icon = {
  up: (size = 18) => svg(<path d="M12 19V5M5 12l7-7 7 7" />, size),
  down: (size = 18) => svg(<path d="M12 5v14M19 12l-7 7-7-7" />, size),
  comment: (size = 15) => svg(<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />, size),
  share: (size = 15) =>
    svg(
      <>
        <circle cx="18" cy="5" r="3" />
        <circle cx="6" cy="12" r="3" />
        <circle cx="18" cy="19" r="3" />
        <path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" />
      </>,
      size,
    ),
  award: (size = 15) =>
    svg(
      <>
        <circle cx="12" cy="8" r="6" />
        <path d="M15.5 13.5L17 22l-5-3-5 3 1.5-8.5" />
      </>,
      size,
    ),
  more: (size = 15) =>
    svg(
      <>
        <circle cx="12" cy="12" r="1" />
        <circle cx="19" cy="12" r="1" />
        <circle cx="5" cy="12" r="1" />
      </>,
      size,
    ),
  search: (size = 15) =>
    svg(
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="M21 21l-4.3-4.3" />
      </>,
      size,
    ),
  bell: (size = 17) =>
    svg(
      <>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </>,
      size,
    ),
  gear: (size = 16) =>
    svg(
      <>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 7 2.6h.1A1.7 1.7 0 0 0 8.3 1V1a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 15 2.6a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1.7z" />
      </>,
      size,
    ),
  plus: (size = 16) => svg(<path d="M12 5v14M5 12h14" />, size),
  close: (size = 18) => svg(<path d="M18 6L6 18M6 6l12 12" />, size),
  refresh: (size = 15) =>
    svg(
      <>
        <path d="M21 2v6h-6" />
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
        <path d="M3 22v-6h6" />
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
      </>,
      size,
    ),
  spark: (size = 15) => svg(<path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4z" />, size),
  flag: (size = 15) => svg(<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7" />, size),
  trash: (size = 15) => svg(<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" />, size),
  lock: (size = 13) =>
    svg(
      <>
        <rect x="3" y="11" width="18" height="11" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </>,
      size,
    ),
  bookmark: (size = 15, filled = false) => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z" />
    </svg>
  ),
};

/* ----------------------------------------------------------------- avatar */

export function Avatar({
  color = '#ff4500',
  emoji = '👤',
  size = 24,
}: {
  color?: string;
  emoji?: string;
  size?: number;
}) {
  return (
    <span
      className="avatar"
      style={{ background: color, width: size, height: size, fontSize: size * 0.55 }}
      aria-hidden="true"
    >
      {emoji}
    </span>
  );
}

/**
 * The "human" capsule.
 *
 * The backend only ever emits a badge for real accounts; simulated users return
 * null and therefore render nothing at all. That asymmetry is intentional — you
 * can spot the people, never the machines.
 */
export function HumanBadge({ badge, show = true }: { badge: AuthorBadge; show?: boolean }) {
  if (!badge || !show) return null;
  return (
    <span className="human-tag" title={badge.title}>
      <span aria-hidden="true">◉</span>
      {badge.label}
    </span>
  );
}

/* ------------------------------------------------------------------- body */

export function Body({ text, className = '' }: { text: string; className?: string }) {
  return (
    <div className={className} dangerouslySetInnerHTML={{ __html: renderBody(text) }} />
  );
}

export function RemovedStub({
  reason,
  by,
  deletedByAuthor = false,
}: {
  reason?: string;
  by?: string | null;
  deletedByAuthor?: boolean;
}) {
  if (deletedByAuthor) {
    return <div className="removed-stub">[deleted by the person who wrote it]</div>;
  }
  return (
    <div>
      <div className="removed-stub">
        Comment removed by moderator{by ? ` ${by}` : ''}
        {reason ? ` — ${reason}` : ''}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ modal */

export function Modal({
  title,
  onClose,
  children,
  footer,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="presentation"
    >
      <div className={`modal${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="btn-icon" onClick={onClose} aria-label="Close">
            {Icon.close()}
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- controls */

export function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`switch${checked ? ' on' : ''}`}
      onClick={() => onChange(!checked)}
    />
  );
}

export function Slider({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.05,
  format,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  format?: (value: number) => string;
}) {
  return (
    <div className="slider-row">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      <span className="slider-value">{format ? format(value) : value.toFixed(2)}</span>
    </div>
  );
}

export function ChipInput({
  values,
  onChange,
  placeholder = 'Add and press Enter',
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState('');

  const commit = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft('');
  };

  return (
    <div className="chip-input">
      {values.map((value) => (
        <span className="chip" key={value}>
          {value}
          <button
            type="button"
            onClick={() => onChange(values.filter((item) => item !== value))}
            aria-label={`Remove ${value}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            commit();
          } else if (event.key === 'Backspace' && !draft && values.length) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={commit}
      />
    </div>
  );
}

export function Dropdown({
  trigger,
  children,
  align = 'right',
}: {
  trigger: (open: boolean) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: 'left' | 'right';
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div className="dropdown" ref={ref}>
      <button type="button" onClick={() => setOpen((value) => !value)} className="btn-ghost">
        {trigger(open)}
      </button>
      {open ? (
        <div className="dropdown-menu" style={align === 'left' ? { left: 0, right: 'auto' } : undefined}>
          {children(() => setOpen(false))}
        </div>
      ) : null}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="spinner" />
      {label ? <span className="muted small">{label}</span> : null}
    </span>
  );
}

export function Empty({ emoji = '🫥', title, hint }: { emoji?: string; title: string; hint?: string }) {
  return (
    <div className="empty">
      <span className="emoji">{emoji}</span>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {hint ? <div className="small">{hint}</div> : null}
    </div>
  );
}

export function SkeletonPost() {
  return (
    <div className="post">
      <div className="votebox" />
      <div className="post-main">
        <div className="skeleton" style={{ height: 11, width: '38%', marginBottom: 9 }} />
        <div className="skeleton" style={{ height: 17, width: '76%', marginBottom: 9 }} />
        <div className="skeleton" style={{ height: 11, width: '92%', marginBottom: 5 }} />
        <div className="skeleton" style={{ height: 11, width: '64%' }} />
      </div>
    </div>
  );
}
