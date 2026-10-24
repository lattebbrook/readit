import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, getToken, setToken } from '../lib/api';

const fetchMock = vi.fn();

function respond(body: unknown, status = 200) {
  fetchMock.mockResolvedValueOnce({
    ok: status < 400,
    status,
    text: async () => JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  // Node exposes its own `localStorage` global that shadows jsdom's and lacks
  // `clear()`, so reset through the module's own accessor instead.
  setToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('token storage', () => {
  it('round-trips and clears', () => {
    expect(getToken()).toBeNull();
    setToken('abc123');
    expect(getToken()).toBe('abc123');
    setToken(null);
    expect(getToken()).toBeNull();
  });

  it('survives storage being unavailable', () => {
    const store = globalThis.localStorage;
    const original = store.setItem.bind(store);
    store.setItem = () => {
      throw new Error('private mode');
    };
    expect(() => setToken('x')).not.toThrow();
    store.setItem = original;
  });
});

describe('request plumbing', () => {
  it('attaches the bearer token when signed in', async () => {
    setToken('tok');
    respond({ ok: true });
    await api.health();

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBe('Bearer tok');
    expect(options.headers['Content-Type']).toBe('application/json');
  });

  it('omits the header when signed out', async () => {
    respond({ ok: true });
    await api.health();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
  });

  it('surfaces the server detail message', async () => {
    respond({ detail: 'That username is taken.' }, 400);
    await expect(api.auth.register('a@b.com', 'hunter22', 'sam')).rejects.toThrow(
      'That username is taken.',
    );
  });

  it('falls back to a status message when there is no detail', async () => {
    respond({}, 503);
    await expect(api.health()).rejects.toMatchObject({ status: 503 });
  });

  it('raises ApiError carrying the status code', async () => {
    respond({ detail: 'Admins only.' }, 403);
    await expect(api.admin.world()).rejects.toBeInstanceOf(ApiError);
  });

  it('handles an empty response body', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, text: async () => '' });
    await expect(api.health()).resolves.toBeNull();
  });
});

describe('endpoint shapes', () => {
  it('builds feed queries', async () => {
    respond({ posts: [], has_more: false });
    await api.feed('home', 'top', 10, 20);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/feed?scope=home&sort=top&limit=10&skip=20');
  });

  it('encodes search terms', async () => {
    respond({ posts: [], boards: [] });
    await api.search('sourdough & rye');
    expect(fetchMock.mock.calls[0][0]).toContain('q=sourdough%20%26%20rye');
  });

  it('posts a vote with the direction', async () => {
    respond({ score: 1, ups: 1, downs: 0, direction: 1 });
    await api.vote('comment', 'c1', -1);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/vote/comment/c1');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ direction: -1 });
  });

  it('requests a thread with sort and wait flags', async () => {
    respond({ post: {}, board: null, comments: [], generated: 0, server_time: 0 });
    await api.posts.get('p1', 'new', false);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/posts/p1?sort=new&wait=false');
  });

  it('polls updates from a checkpoint', async () => {
    respond({ changed: false, new_comments: 0, post: {}, server_time: 1, generating: false });
    await api.posts.updates('p1', 1234.5, 'best');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/posts/p1/updates?since=1234.5&sort=best');
  });

  it('sends a top-level comment with a null parent', async () => {
    respond({ comment: {} });
    await api.posts.comment('p1', 'hello');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      body: 'hello',
      parent_id: null,
      generate_replies: true,
    });
  });

  it('wipes with the confirmation word the server demands', async () => {
    respond({ posts_wiped: 0, comments_wiped: 0, account_deleted: false });
    await api.me.wipe(true);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      delete_account: true,
      confirm: 'WIPE',
    });
  });

  it('uses DELETE for unsubscribing', async () => {
    respond({ user: {} });
    await api.me.unsubscribe('funny');
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE');
  });

  it('sets a board personal prompt with PUT', async () => {
    respond({ prompt: 'x' });
    await api.boards.setPersonalPrompt('funny', 'lean technical');
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/boards/funny/personal-prompt');
    expect(options.method).toBe('PUT');
  });

  it('patches world config for admins', async () => {
    respond({ world: {} });
    await api.admin.updateWorld({ toxicity: 0.9 });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/admin/world');
    expect(options.method).toBe('PATCH');
    expect(JSON.parse(options.body)).toEqual({ toxicity: 0.9 });
  });
});
