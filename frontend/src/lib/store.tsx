import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api, setToken } from './api';
import type { Preferences, SiteInfo, User } from './types';

interface Toast {
  id: number;
  message: string;
  tone: 'info' | 'error' | 'success';
}

interface AppState {
  user: User | null;
  site: SiteInfo | null;
  loading: boolean;
  unread: number;
  toasts: Toast[];
  refresh: () => Promise<void>;
  refreshUnread: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, username: string) => Promise<void>;
  continueAsGuest: (hint?: string) => Promise<void>;
  upgradeGuest: (email: string, password: string, username: string) => Promise<void>;
  signOut: () => Promise<void>;
  setUser: (user: User | null) => void;
  updatePreferences: (changes: Partial<Preferences>) => Promise<void>;
  toggleSubscription: (name: string, subscribed: boolean) => Promise<void>;
  notify: (message: string, tone?: Toast['tone']) => void;
  dismissToast: (id: number) => void;
}

const AppContext = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [site, setSite] = useState<SiteInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [unread, setUnread] = useState(0);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const notify = useCallback((message: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message, tone }]);
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 4200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const info = await api.site();
      setSite(info);
      setUser(info.user);
    } catch {
      setSite(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshUnread = useCallback(async () => {
    if (!user) {
      setUnread(0);
      return;
    }
    try {
      const { unread: count } = await api.me.inbox(true);
      setUnread(count);
    } catch {
      /* inbox is best-effort */
    }
  }, [user]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    void refreshUnread();
    if (!user) return;
    const timer = setInterval(() => void refreshUnread(), 45_000);
    return () => clearInterval(timer);
  }, [user, refreshUnread]);

  // Theme is a user preference but must apply before any account loads.
  useEffect(() => {
    const theme = user?.preferences?.theme ?? localStorage.getItem('readit.theme') ?? 'dark';
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('readit.theme', theme);
  }, [user]);

  useEffect(() => {
    document.documentElement.dataset.compact = user?.preferences?.compact_mode ? 'true' : 'false';
  }, [user]);

  useEffect(() => {
    const size = user?.preferences?.content_font_size ?? 13;
    const family = user?.preferences?.content_font_family?.trim();
    const root = document.documentElement.style;
    root.setProperty('--content-font-size', `${size}px`);
    root.setProperty('--content-font-family', family ? `"${family}", sans-serif` : 'inherit');
  }, [user]);

  const adopt = useCallback(
    async (result: { token: string; user: User }) => {
      setToken(result.token);
      setUser(result.user);
      await refresh();
    },
    [refresh],
  );

  const value = useMemo<AppState>(
    () => ({
      user,
      site,
      loading,
      unread,
      toasts,
      refresh,
      refreshUnread,
      setUser,
      notify,
      dismissToast,
      signIn: async (email, password) => adopt(await api.auth.login(email, password)),
      signUp: async (email, password, username) =>
        adopt(await api.auth.register(email, password, username)),
      continueAsGuest: async (hint = '') => adopt(await api.auth.guest(hint)),
      upgradeGuest: async (email, password, username) =>
        adopt(await api.auth.promote(email, password, username)),
      signOut: async () => {
        try {
          await api.auth.logout();
        } finally {
          setToken(null);
          setUser(null);
          await refresh();
        }
      },
      updatePreferences: async (changes) => {
        const { user: updated } = await api.me.preferences(changes as Record<string, unknown>);
        setUser(updated);
      },
      toggleSubscription: async (name, subscribed) => {
        const { user: updated } = subscribed
          ? await api.me.unsubscribe(name)
          : await api.me.subscribe(name);
        setUser(updated);
      },
    }),
    [user, site, loading, unread, toasts, refresh, refreshUnread, adopt, notify, dismissToast],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppState {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used inside <AppProvider>');
  return context;
}
