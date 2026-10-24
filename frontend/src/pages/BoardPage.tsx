import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { BoardSettingsModal } from '../components/BoardModals';
import { PhotoGrid } from '../components/Media';
import { PostList } from '../components/PostCard';
import { Avatar, Empty, Icon, SkeletonPost } from '../components/common';
import { useRail } from '../components/Layout';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import type { Board, Post, User } from '../lib/types';

const SORTS = ['hot', 'new', 'top', 'rising', 'controversial'];

function BoardRail({
  board,
  onOpenSettings,
  onStir,
  stirring,
}: {
  board: Board;
  onOpenSettings: () => void;
  onStir: () => void;
  stirring: boolean;
}) {
  const [members, setMembers] = useState<User[]>([]);
  const [modLog, setModLog] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void api.boards.members(board.name).then((data) => setMembers(data.members)).catch(() => {});
    void api.boards.modLog(board.name).then((data) => setModLog(data.entries.slice(0, 6))).catch(() => {});
  }, [board.name]);

  return (
    <>
      <div className="card card-pad">
        <div className="row-between">
          <p className="card-title" style={{ margin: 0 }}>
            About r/{board.name}
          </p>
          <button className="btn-icon" onClick={onOpenSettings} title="Board settings" aria-label="Board settings">
            {Icon.gear()}
          </button>
        </div>
        <p className="small" style={{ marginTop: 8 }}>
          {board.description || 'No description yet.'}
        </p>
        {board.sidebar ? <p className="small muted">{board.sidebar}</p> : null}
        <div className="divider" />
        <dl className="kv">
          <dt>Members</dt>
          <dd>{formatScore(board.subscribers)}</dd>
          <dt>Here now</dt>
          <dd style={{ color: 'var(--ok)' }}>{formatScore(board.members_online)}</dd>
          <dt>Posts</dt>
          <dd>{board.post_count}</dd>
          <dt>Created</dt>
          <dd>{new Date(board.created_at * 1000).toLocaleDateString()}</dd>
        </dl>
        {board.creator_username ? (
          <p className="tiny muted" style={{ marginTop: 8 }}>
            Created by <Link to={`/u/${board.creator_username}`}>u/{board.creator_username}</Link>
          </p>
        ) : null}
        <Link
          to={`/submit?board=${board.name}`}
          className="btn btn-primary"
          style={{ width: '100%', marginTop: 12 }}
        >
          Create a post
        </Link>
        {/* Nothing to summon on a photo board — the regulars have no pictures
            to post, so threads here start with a capture. */}
        {board.kind === 'photo' ? (
          <p className="tiny faint" style={{ marginTop: 10, marginBottom: 0 }}>
            Post a picture and the regulars turn up to pick it apart.
          </p>
        ) : (
          <button
            className="btn btn-outline btn-sm"
            style={{ width: '100%', marginTop: 8 }}
            onClick={onStir}
            disabled={stirring}
          >
            {stirring ? 'writing…' : 'Summon new posts'}
          </button>
        )}
      </div>

      {board.rules.length ? (
        <div className="card card-pad">
          <p className="card-title">Rules</p>
          <ol className="small" style={{ paddingLeft: 18, margin: 0 }}>
            {board.rules.map((rule, index) => (
              <li key={index} style={{ marginBottom: 4 }}>
                {rule}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="card card-pad">
        <p className="card-title">Moderators</p>
        <div className="stack" style={{ gap: 4 }}>
          {board.moderators.map((name) => (
            <Link to={`/u/${name}`} key={name} className="small">
              u/{name}
            </Link>
          ))}
        </div>
      </div>

      {members.length ? (
        <div className="card card-pad">
          <p className="card-title">Regulars</p>
          <div className="row wrap" style={{ gap: 6 }}>
            {members.slice(0, 16).map((member) => (
              <Link to={`/u/${member.username}`} key={member.id} title={`u/${member.username}`}>
                <Avatar color={member.avatar_color} emoji={member.avatar_emoji} size={26} />
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      {modLog.length ? (
        <div className="card card-pad">
          <p className="card-title">Public mod log</p>
          <div className="stack" style={{ gap: 6 }}>
            {modLog.map((entry, index) => (
              <div className="tiny muted" key={index}>
                <strong>{String(entry.moderator)}</strong> {String(entry.action).replace('_', ' ')} —{' '}
                {String(entry.reason)}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}

export function BoardPage() {
  const { name = '' } = useParams();
  const { user, notify, toggleSubscription } = useApp();
  const [board, setBoard] = useState<Board | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [sort, setSort] = useState('hot');
  const [loading, setLoading] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [stirring, setStirring] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.boards.posts(name, sort, 30);
      setBoard(data.board);
      setPosts(data.posts);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load that board.');
    } finally {
      setLoading(false);
    }
  }, [name, sort]);

  useEffect(() => {
    void load();
  }, [load]);

  const stir = async () => {
    setStirring(true);
    try {
      await api.boards.generate(name, 4);
      notify('Fresh posts have landed.', 'success');
      await load();
    } catch {
      notify('The board stayed quiet. Try again.', 'error');
    } finally {
      setStirring(false);
    }
  };

  useRail(
    board ? (
      <BoardRail
        board={board}
        onOpenSettings={() => setSettingsOpen(true)}
        onStir={() => void stir()}
        stirring={stirring}
      />
    ) : null,
    [board, stirring],
  );

  if (error) {
    return (
      <div className="card">
        <Empty emoji="🚧" title={error} hint="Try another board from the sidebar." />
      </div>
    );
  }

  const subscribed = board?.subscribed ?? false;

  return (
    <>
      {board ? (
        <div className="board-banner">
          <div className="board-banner-top" style={{ background: board.color }} />
          <div className="board-banner-body">
            <span className="board-icon" style={{ background: board.color }}>
              {board.icon}
            </span>
            <div className="board-heading grow">
              <h1>{board.title || board.name}</h1>
              <span className="handle">
                r/{board.name} · {formatScore(board.subscribers)} members ·{' '}
                <span style={{ color: 'var(--ok)' }}>{formatScore(board.members_online)} here now</span>
              </span>
            </div>
            <div className="row" style={{ gap: 8 }}>
              {board.nsfw ? <span className="flair tag-nsfw">NSFW</span> : null}
              <button
                className={`btn ${subscribed ? 'btn-outline' : 'btn-primary'}`}
                onClick={async () => {
                  if (!user) {
                    notify('Sign in or continue as a guest to join.', 'error');
                    return;
                  }
                  await toggleSubscription(board.name, subscribed);
                  setBoard({
                    ...board,
                    subscribed: !subscribed,
                    subscribers: board.subscribers + (subscribed ? -1 : 1),
                  });
                }}
              >
                {subscribed ? 'Joined' : 'Join'}
              </button>
              <button
                className="btn-icon"
                onClick={() => setSettingsOpen(true)}
                title="Board settings"
                aria-label="Board settings"
              >
                {Icon.gear()}
              </button>
            </div>
          </div>
        </div>
      ) : null}

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
      </div>

      {loading ? (
        <div className="post-list">
          {[0, 1, 2].map((index) => (
            <SkeletonPost key={index} />
          ))}
        </div>
      ) : posts.length ? (
        board?.kind === 'photo' ? (
          <PhotoGrid posts={posts} />
        ) : (
          <PostList
            posts={posts}
            onChanged={(updated) =>
              setPosts((current) => current.map((post) => (post.id === updated.id ? updated : post)))
            }
          />
        )
      ) : (
        <div className="card">
          <Empty
            emoji={board?.kind === 'photo' ? '📷' : '👻'}
            title={
              board?.kind === 'photo'
                ? 'No pictures here yet'
                : 'Nobody has posted here yet'
            }
            hint={
              board?.kind === 'photo'
                ? 'Photo boards start with you — post an image and the regulars will show up to argue about it.'
                : 'Hit “Summon new posts” in the sidebar, or write the first one yourself.'
            }
          />
        </div>
      )}

      {settingsOpen && board ? (
        <BoardSettingsModal
          board={board}
          onClose={() => setSettingsOpen(false)}
          onSaved={(updated) => setBoard(updated)}
        />
      ) : null}
    </>
  );
}
