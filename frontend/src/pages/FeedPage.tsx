import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { PostList } from '../components/PostCard';
import { Empty, Icon, SkeletonPost } from '../components/common';
import { useRail } from '../components/Layout';
import { api } from '../lib/api';
import { useApp } from '../lib/store';
import type { Board, Post } from '../lib/types';

const SORTS = ['hot', 'new', 'top', 'rising', 'best', 'controversial'];

function Rail({ scope }: { scope: string }) {
  const { user, site, toggleSubscription } = useApp();
  const [recommended, setRecommended] = useState<Board[]>([]);
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void api.boards.recommended().then((data) => setRecommended(data.boards)).catch(() => {});
  }, [user?.interests?.length, user?.subscriptions?.length]);

  useEffect(() => {
    const load = () => void api.activity().then((data) => setEvents(data.events.slice(0, 8))).catch(() => {});
    load();
    const timer = setInterval(load, 20_000);
    return () => clearInterval(timer);
  }, []);

  return (
    <>
      <div className="card card-pad">
        <p className="card-title">About ReadIt</p>
        <p className="small muted" style={{ marginTop: 0 }}>
          {site?.description || 'The front page of a very fake internet.'}
        </p>
        <div className="divider" />
        <dl className="kv">
          <dt>Boards</dt>
          <dd>{site?.counts.boards ?? 0}</dd>
          <dt>Posts</dt>
          <dd>{site?.counts.posts ?? 0}</dd>
          <dt>Comments</dt>
          <dd>{site?.counts.comments ?? 0}</dd>
          <dt>Readizen</dt>
          <dd>120M</dd>
        </dl>
        <Link to="/submit" className="btn btn-primary" style={{ width: '100%', marginTop: 12 }}>
          Create a post
        </Link>
      </div>

      {scope === 'home' && recommended.length ? (
        <div className="card card-pad">
          <p className="card-title">Because of your interests</p>
          <div className="stack" style={{ gap: 8 }}>
            {recommended.slice(0, 6).map((board) => (
              <div className="row-between" key={board.id}>
                <Link to={`/r/${board.name}`} className="row grow" style={{ gap: 8, minWidth: 0 }}>
                  <span className="sub-dot" style={{ background: board.color }}>
                    {board.icon}
                  </span>
                  <span className="grow" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    <div style={{ fontWeight: 700 }}>r/{board.name}</div>
                    <div className="tiny muted" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {board.description}
                    </div>
                  </span>
                </Link>
                <button
                  className="btn btn-outline btn-sm"
                  onClick={() => void toggleSubscription(board.name, false)}
                >
                  Join
                </button>
              </div>
            ))}
          </div>
          <Link to="/settings?tab=feed" className="small" style={{ display: 'block', marginTop: 10 }}>
            Edit your interests →
          </Link>
        </div>
      ) : null}

      {events.length ? (
        <div className="card card-pad">
          <p className="card-title row" style={{ gap: 6 }}>
            <span className="live-dot" /> Happening now
          </p>
          <div className="stack" style={{ gap: 6 }}>
            {events.map((event, index) => (
              <div className="tiny muted" key={index}>
                {event.kind === 'post' ? '📝 new post in ' : event.kind === 'share' ? '🔗 shared in ' : '💬 replies in '}
                <strong>r/{String(event.subreddit ?? '…')}</strong>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

export function FeedPage({ scope = 'home' }: { scope?: 'home' | 'popular' }) {
  const { user, notify } = useApp();
  const [posts, setPosts] = useState<Post[]>([]);
  const [sort, setSort] = useState(user?.preferences?.feed_sort ?? 'hot');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useRail(<Rail scope={scope} />, [scope, user?.interests?.length, user?.subscriptions?.length]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.feed(scope, sort, 30);
      setPosts(data.posts);
    } catch {
      notify('Could not load the feed.', 'error');
    } finally {
      setLoading(false);
    }
  }, [scope, sort, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  // The world keeps writing while you read; pick up new arrivals quietly.
  useEffect(() => {
    if (!(user?.preferences?.live_updates ?? true)) return;
    const timer = setInterval(async () => {
      try {
        const data = await api.feed(scope, sort, 30);
        setPosts(data.posts);
      } catch {
        /* transient */
      }
    }, 30_000);
    return () => clearInterval(timer);
  }, [scope, sort, user?.preferences?.live_updates]);

  const stir = async () => {
    setRefreshing(true);
    try {
      const boards = user?.subscriptions?.length
        ? user.subscriptions
        : (await api.boards.list()).boards.slice(0, 3).map((board) => board.name);
      const target = boards[Math.floor(Math.random() * boards.length)];
      if (target) {
        await api.boards.generate(target, 3);
        notify(`New posts landed in r/${target}.`, 'success');
        await load();
      }
    } catch {
      notify('Nobody had anything to say. Try again.', 'error');
    } finally {
      setRefreshing(false);
    }
  };

  const updatePost = (updated: Post) =>
    setPosts((current) => current.map((post) => (post.id === updated.id ? updated : post)));

  return (
    <>
      <div className="tabs">
        {SORTS.map((option) => (
          <button
            key={option}
            className={`tab${sort === option ? ' active' : ''}`}
            onClick={() => setSort(option)}
          >
            {option}
          </button>
        ))}
        <span className="grow" />
        <button className="btn btn-ghost btn-sm" onClick={() => void stir()} disabled={refreshing}>
          {Icon.refresh()} {refreshing ? 'stirring…' : 'stir the pot'}
        </button>
      </div>

      {loading ? (
        <div className="post-list">
          {[0, 1, 2, 3].map((index) => (
            <SkeletonPost key={index} />
          ))}
        </div>
      ) : posts.length ? (
        <PostList posts={posts} onChanged={updatePost} />
      ) : (
        <div className="card">
          <Empty
            emoji="🌵"
            title={scope === 'home' ? 'Your home feed is empty' : 'Nothing here yet'}
            hint={
              scope === 'home'
                ? 'Join a few boards, or hit "stir the pot" and give the site a minute to write something.'
                : 'Press "stir the pot" to summon some posts.'
            }
          />
        </div>
      )}
    </>
  );
}
