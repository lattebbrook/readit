import type {
  Award,
  Board,
  Comment,
  ImageAnalysis,
  LLMConfig,
  Media,
  Notification,
  Post,
  SiteInfo,
  User,
  WorldConfig,
} from './types';

const TOKEN_KEY = 'readit.token';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode) — session stays in memory only */
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail = payload?.detail;
    throw new ApiError(
      typeof detail === 'string' ? detail : `Request failed (${response.status})`,
      response.status,
    );
  }
  return payload as T;
}

const get = <T,>(path: string) => request<T>(path);
const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(body) });
const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'PUT', body: JSON.stringify(body) });
const del = <T,>(path: string) => request<T>(path, { method: 'DELETE' });

export const api = {
  site: () => get<SiteInfo>('/api/site'),
  health: () => get<Record<string, unknown>>('/api/health'),

  auth: {
    me: () => get<{ user: User | null; authenticated: boolean }>('/api/auth/me'),
    register: (email: string, password: string, username: string) =>
      post<{ token: string; user: User }>('/api/auth/register', { email, password, username }),
    login: (email: string, password: string) =>
      post<{ token: string; user: User }>('/api/auth/login', { email, password }),
    guest: (displayHint = '') =>
      post<{ token: string; user: User }>('/api/auth/guest', { display_hint: displayHint }),
    promote: (email: string, password: string, username: string) =>
      post<{ token: string; user: User }>('/api/auth/promote', { email, password, username }),
    logout: () => post<{ ok: boolean }>('/api/auth/logout'),
    usernameAvailable: (username: string) =>
      get<{ available: boolean }>(`/api/auth/username-available?username=${encodeURIComponent(username)}`),
  },

  me: {
    profile: (changes: Partial<User>) => patch<{ user: User }>('/api/me/profile', changes),
    preferences: (preferences: Record<string, unknown>) =>
      patch<{ user: User }>('/api/me/preferences', { preferences }),
    interests: (interests: string[]) => put<{ user: User }>('/api/me/interests', { interests }),
    subscribe: (name: string) => post<{ user: User }>(`/api/me/subscriptions/${name}`),
    unsubscribe: (name: string) => del<{ user: User }>(`/api/me/subscriptions/${name}`),
    blockBoard: (name: string) => post<{ user: User }>(`/api/me/blocked-boards/${name}`),
    unblockBoard: (name: string) => del<{ user: User }>(`/api/me/blocked-boards/${name}`),
    savedPosts: () => get<{ posts: Post[] }>('/api/me/saved'),
    savePost: (id: string) => post<{ user: User; saved: boolean }>(`/api/me/saved/${id}`),
    unsavePost: (id: string) => del<{ user: User; saved: boolean }>(`/api/me/saved/${id}`),
    inbox: (unreadOnly = false) =>
      get<{ notifications: Notification[]; unread: number }>(
        `/api/me/inbox?unread_only=${unreadOnly}`,
      ),
    markAllRead: () => post<{ marked: number }>('/api/me/inbox/read'),
    clearInbox: () => del<{ cleared: number }>('/api/me/inbox'),
    exportData: () => get<Record<string, unknown>>('/api/me/export'),
    wipe: (deleteAccount: boolean) =>
      post<{ posts_wiped: number; comments_wiped: number; account_deleted: boolean }>('/api/me/wipe', {
        delete_account: deleteAccount,
        confirm: 'WIPE',
      }),
  },

  boards: {
    list: (query = '', sort = 'subscribers') =>
      get<{ boards: Board[] }>(`/api/boards?q=${encodeURIComponent(query)}&sort=${sort}`),
    recommended: () => get<{ boards: Board[] }>('/api/boards/recommended'),
    get: (name: string) => get<{ board: Board }>(`/api/boards/${name}`),
    posts: (name: string, sort = 'hot', limit = 25, skip = 0) =>
      get<{ board: Board; posts: Post[]; sort: string }>(
        `/api/boards/${name}/posts?sort=${sort}&limit=${limit}&skip=${skip}`,
      ),
    create: (payload: Record<string, unknown>) =>
      post<{ board: Board; preparing: boolean }>('/api/boards', payload),
    update: (name: string, changes: Record<string, unknown>) =>
      patch<{ board: Board }>(`/api/boards/${name}`, changes),
    remove: (name: string) => del<{ deleted: boolean }>(`/api/boards/${name}`),
    setPersonalPrompt: (name: string, prompt: string) =>
      put<{ prompt: string }>(`/api/boards/${name}/personal-prompt`, { prompt }),
    generate: (name: string, count?: number) =>
      post<{ posts: Post[] }>(`/api/boards/${name}/generate`, { count }),
    members: (name: string) =>
      get<{ members: User[]; online: number }>(`/api/boards/${name}/members`),
    modLog: (name: string) =>
      get<{ entries: Record<string, unknown>[] }>(`/api/boards/${name}/mod-log`),
  },

  media: {
    /** Multipart upload — used by the file picker, paste, and drag-and-drop. */
    upload: async (file: File | Blob, board = ''): Promise<{ media: Media }> => {
      const form = new FormData();
      form.append('file', file, (file as File).name || 'pasted.png');
      const headers: Record<string, string> = {};
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      // No Content-Type here on purpose: the browser must set the
      // multipart boundary itself.
      const response = await fetch(`/api/media/upload?board=${encodeURIComponent(board)}`, {
        method: 'POST',
        headers,
        body: form,
      });
      const text = await response.text();
      const payload = text ? JSON.parse(text) : null;
      if (!response.ok) {
        throw new ApiError(payload?.detail ?? `Upload failed (${response.status})`, response.status);
      }
      return payload;
    },
    fromUrl: (url: string, board = '', sourcePage = '') =>
      post<{ media: Media }>('/api/media/from-url', {
        url,
        board,
        source_page: sourcePage,
      }),
    analysis: (id: string) =>
      get<{ state: string; model: string; analysis: ImageAnalysis | null }>(
        `/api/media/${id}/analysis`,
      ),
    describe: (id: string, board = '', force = false) =>
      post<{ analysis: ImageAnalysis }>(
        `/api/media/${id}/describe?board=${encodeURIComponent(board)}&force=${force}`,
      ),
  },

  feed: (scope = 'home', sort = 'hot', limit = 25, skip = 0) =>
    get<{ posts: Post[]; has_more: boolean }>(
      `/api/feed?scope=${scope}&sort=${sort}&limit=${limit}&skip=${skip}`,
    ),

  search: (query: string, subreddit?: string) =>
    get<{ posts: Post[]; boards: Board[] }>(
      `/api/search?q=${encodeURIComponent(query)}${subreddit ? `&subreddit=${subreddit}` : ''}`,
    ),

  posts: {
    create: (payload: Record<string, unknown>) => post<{ post: Post }>('/api/posts', payload),
    get: (id: string, sort = 'best', wait = true) =>
      get<{
        post: Post;
        board: Board | null;
        comments: Comment[];
        generated: number;
        server_time: number;
      }>(`/api/posts/${id}?sort=${sort}&wait=${wait}`),
    updates: (id: string, since: number, sort = 'best') =>
      get<{
        changed: boolean;
        new_comments: number;
        post: Post;
        comments?: Comment[];
        server_time: number;
        generating: boolean;
      }>(`/api/posts/${id}/updates?since=${since}&sort=${sort}`),
    generate: (id: string, count?: number, focus?: string) =>
      post<{ created: number; comments: Comment[]; post: Post }>(`/api/posts/${id}/generate`, {
        count,
        focus,
      }),
    comment: (id: string, body: string, parentId?: string | null) =>
      post<{ comment: Comment }>(`/api/posts/${id}/comments`, {
        body,
        parent_id: parentId ?? null,
        generate_replies: true,
      }),
    edit: (id: string, changes: { title?: string; body?: string }) =>
      patch<{ post: Post }>(`/api/posts/${id}`, changes),
    remove: (id: string) => del<{ post: Post }>(`/api/posts/${id}`),
  },

  comments: {
    edit: (id: string, body: string) => patch<{ comment: Comment }>(`/api/comments/${id}`, { body }),
    remove: (id: string) => del<{ comment: Comment }>(`/api/comments/${id}`),
    summonReplies: (id: string, count?: number) =>
      post<{ created: number; comments: Comment[] }>(`/api/comments/${id}/replies`, { count }),
  },

  vote: (kind: 'post' | 'comment', id: string, direction: number) =>
    post<{ score: number; ups: number; downs: number; direction: number }>(
      `/api/vote/${kind}/${id}`,
      { direction },
    ),

  awards: {
    catalogue: () => get<{ awards: Award[]; coins: number }>('/api/awards'),
    give: (kind: 'post' | 'comment', id: string, awardId: string, anonymous = false) =>
      post<{ award: Award; awards: Award[]; coins: number }>(`/api/award/${kind}/${id}`, {
        award_id: awardId,
        anonymous,
      }),
  },

  share: (kind: 'post' | 'comment', id: string) =>
    post<{ url: string; shares: number }>(`/api/share/${kind}/${id}`),

  report: (kind: 'post' | 'comment', id: string, reason: string) =>
    post<{ message: string }>(`/api/report/${kind}/${id}`, { reason }),

  user: (username: string) =>
    get<{ profile: User; posts: Post[]; comments: Comment[]; is_self: boolean }>(
      `/api/users/${username}`,
    ),

  activity: () => get<{ events: Record<string, unknown>[] }>('/api/activity'),

  admin: {
    world: () => get<{ world: WorldConfig }>('/api/admin/world'),
    updateWorld: (changes: Record<string, unknown>) =>
      patch<{ world: WorldConfig }>('/api/admin/world', changes),
    resetWorld: () => post<{ world: WorldConfig }>('/api/admin/world/reset'),
    llm: () =>
      get<{
        config: LLMConfig;
        provider_types: string[];
        suggested_models: Record<string, string[]>;
        stats: Record<string, unknown>;
      }>('/api/admin/llm'),
    addConnection: (payload: Record<string, unknown>) =>
      post<{ config: LLMConfig }>('/api/admin/llm/connections', payload),
    updateConnection: (id: string, changes: Record<string, unknown>) =>
      patch<{ config: LLMConfig }>(`/api/admin/llm/connections/${id}`, changes),
    deleteConnection: (id: string) =>
      del<{ config: LLMConfig }>(`/api/admin/llm/connections/${id}`),
    testConnection: (id: string, model?: string) =>
      post<{ ok: boolean; latency_ms: number; error: string | null; sample: string }>(
        `/api/admin/llm/connections/${id}/test`,
        { model },
      ),
    discoverModels: (id: string) =>
      post<{ models: string[]; config: LLMConfig }>(`/api/admin/llm/connections/${id}/models`),
    setRole: (role: string, payload: Record<string, unknown>) =>
      put<{ config: LLMConfig }>(`/api/admin/llm/roles/${role}`, payload),
    setFlags: (payload: Record<string, unknown>) =>
      patch<{ config: LLMConfig }>('/api/admin/llm/flags', payload),
    calls: () =>
      get<{ calls: Record<string, unknown>[]; stats: Record<string, unknown> }>(
        '/api/admin/llm/calls',
      ),
    simulation: () => get<Record<string, unknown>>('/api/admin/simulation'),
    tick: () => post<{ tick: Record<string, unknown> }>('/api/admin/simulation/tick'),
    startSimulation: () => post<Record<string, unknown>>('/api/admin/simulation/start'),
    stopSimulation: () => post<Record<string, unknown>>('/api/admin/simulation/stop'),
    seed: (boardLimit = 6, postsPerBoard = 5) =>
      post<Record<string, unknown>>('/api/admin/seed', {
        board_limit: boardLimit,
        posts_per_board: postsPerBoard,
      }),
    generatePersonas: (count = 10, board?: string) =>
      post<Record<string, unknown>>(
        `/api/admin/personas/generate?count=${count}${board ? `&board=${board}` : ''}`,
      ),
    stats: () => get<Record<string, unknown>>('/api/admin/stats'),
    modLog: () => get<{ entries: Record<string, unknown>[] }>('/api/admin/mod-log'),
    users: () => get<{ users: User[] }>('/api/admin/users'),
    remove: (kind: string, id: string, reason = '') =>
      post<{ removed: boolean }>(
        `/api/admin/moderate/${kind}/${id}/remove?reason=${encodeURIComponent(reason)}`,
      ),
    restore: (kind: string, id: string) =>
      post<{ restored: boolean }>(`/api/admin/moderate/${kind}/${id}/restore`),
    snapshot: () => post<{ path: string }>('/api/admin/snapshot'),
    resetWorldContent: (keepUsers = true) =>
      post<Record<string, unknown>>(`/api/admin/reset-world?keep_users=${keepUsers}`),
  },
};
