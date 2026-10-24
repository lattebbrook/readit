import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useApp } from '../lib/store';
import type { Board } from '../lib/types';
import { api } from '../lib/api';
import { Avatar, Dropdown, Icon } from './common';
import { CreateBoardModal } from './BoardModals';

/* The right-hand rail is owned by whichever page is mounted. */
const RailContext = createContext<(node: ReactNode) => void>(() => {});

export function useRail(node: ReactNode, deps: unknown[]) {
  const setRail = useContext(RailContext);
  useEffect(() => {
    setRail(node);
    return () => setRail(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

function Toasts() {
  const { toasts, dismissToast } = useApp();
  if (!toasts.length) return null;
  return (
    <div className="toasts">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast ${toast.tone}`}
          onClick={() => dismissToast(toast.id)}
          role="status"
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}

function Header({ onCreateBoard }: { onCreateBoard: () => void }) {
  const { user, site, unread, signOut } = useApp();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');

  return (
    <header className="header">
      <Link to="/" className="logo">
        <span className="logo-mark" aria-hidden="true">
          📖
        </span>
        <span>ReadIt</span>
      </Link>

      <form
        className="search"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
        }}
      >
        <span className="search-icon">{Icon.search()}</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search ReadIt"
          aria-label="Search"
        />
      </form>

      <div className="header-actions">
        {site && !site.llm_ready ? (
          <Link
            to="/admin"
            className="pill"
            title="No AI provider connected — running on the offline generator"
          >
            offline mode
          </Link>
        ) : null}

        {user ? (
          <>
            <Link to="/inbox" className="btn-icon" style={{ position: 'relative' }} aria-label="Inbox">
              {Icon.bell()}
              {unread > 0 ? <span className="badge-count">{unread > 99 ? '99+' : unread}</span> : null}
            </Link>
            <Link to="/submit" className="btn btn-ghost" title="Create a post">
              {Icon.plus()}
            </Link>
            <Dropdown
              trigger={() => (
                <span className="row" style={{ gap: 7 }}>
                  <Avatar color={user.avatar_color} emoji={user.avatar_emoji} size={24} />
                  <span className="small" style={{ maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {user.username}
                  </span>
                </span>
              )}
            >
              {(close) => (
                <>
                  <Link className="dropdown-item" to={`/u/${user.username}`} onClick={close}>
                    My profile
                  </Link>
                  <Link className="dropdown-item" to="/saved" onClick={close}>
                    {Icon.bookmark()} Saved
                  </Link>
                  <Link className="dropdown-item" to="/settings" onClick={close}>
                    {Icon.gear()} Settings
                  </Link>
                  <button
                    className="dropdown-item"
                    onClick={() => {
                      close();
                      onCreateBoard();
                    }}
                  >
                    {Icon.plus()} Create a board
                  </button>
                  {user.is_admin ? (
                    <Link className="dropdown-item" to="/admin" onClick={close}>
                      ⚙️ Admin console
                    </Link>
                  ) : null}
                  {user.is_guest ? (
                    <Link className="dropdown-item" to="/settings?tab=account" onClick={close}>
                      ✨ Save this guest account
                    </Link>
                  ) : null}
                  <div className="divider" />
                  <button
                    className="dropdown-item"
                    onClick={() => {
                      close();
                      void signOut();
                    }}
                  >
                    Log out
                  </button>
                </>
              )}
            </Dropdown>
          </>
        ) : (
          <Link to="/login" className="btn btn-primary">
            Log in
          </Link>
        )}
      </div>
    </header>
  );
}

function LeftSidebar({ onCreateBoard }: { onCreateBoard: () => void }) {
  const { user } = useApp();
  const location = useLocation();
  const [boards, setBoards] = useState<Board[]>([]);

  useEffect(() => {
    void api.boards
      .list()
      .then((data) => setBoards(data.boards))
      .catch(() => setBoards([]));
  }, [user?.subscriptions?.length]);

  const subscribed = useMemo(() => {
    const names = new Set(user?.subscriptions ?? []);
    return boards.filter((board) => names.has(board.name));
  }, [boards, user?.subscriptions]);

  const others = useMemo(() => {
    const names = new Set(user?.subscriptions ?? []);
    return boards.filter((board) => !names.has(board.name)).slice(0, 14);
  }, [boards, user?.subscriptions]);

  const renderBoard = (board: Board) => (
    <Link
      key={board.id}
      to={`/r/${board.name}`}
      className={`sub-item${location.pathname.startsWith(`/r/${board.name}`) ? ' active' : ''}`}
    >
      <span className="sub-dot" style={{ background: board.color }}>
        {board.icon}
      </span>
      <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
        r/{board.name}
      </span>
    </Link>
  );

  return (
    <aside className="sidebar-left">
      <div className="card card-pad">
        <div className="stack" style={{ gap: 2 }}>
          <Link to="/" className={`sub-item${location.pathname === '/' ? ' active' : ''}`}>
            <span className="sub-dot" style={{ background: 'var(--surface-3)' }}>
              🏠
            </span>
            Home
          </Link>
          <Link to="/popular" className={`sub-item${location.pathname === '/popular' ? ' active' : ''}`}>
            <span className="sub-dot" style={{ background: 'var(--surface-3)' }}>
              📈
            </span>
            Popular
          </Link>
          <Link to="/boards" className={`sub-item${location.pathname === '/boards' ? ' active' : ''}`}>
            <span className="sub-dot" style={{ background: 'var(--surface-3)' }}>
              🗂️
            </span>
            All boards
          </Link>
        </div>
      </div>

      {subscribed.length ? (
        <div className="card card-pad">
          <p className="card-title">Your boards</p>
          <div className="stack" style={{ gap: 1 }}>{subscribed.map(renderBoard)}</div>
        </div>
      ) : null}

      <div className="card card-pad">
        <p className="card-title">Browse</p>
        <div className="stack" style={{ gap: 1 }}>{others.map(renderBoard)}</div>
        <button className="btn btn-outline btn-sm" style={{ width: '100%', marginTop: 10 }} onClick={onCreateBoard}>
          {Icon.plus()} Create a board
        </button>
      </div>
    </aside>
  );
}

export function Layout() {
  const [rail, setRail] = useState<ReactNode>(null);
  const [creating, setCreating] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <RailContext.Provider value={setRail}>
      <div className="app">
        <Header onCreateBoard={() => setCreating(true)} />
        <main className="shell">
          <LeftSidebar onCreateBoard={() => setCreating(true)} />
          <div className="grow">
            <Outlet />
          </div>
          <aside className="sidebar-right">{rail}</aside>
        </main>
        <Toasts />
        {creating ? (
          <CreateBoardModal
            onClose={() => setCreating(false)}
            onCreated={(board) => {
              setCreating(false);
              navigate(`/r/${board.name}`);
            }}
          />
        ) : null}
      </div>
    </RailContext.Provider>
  );
}
