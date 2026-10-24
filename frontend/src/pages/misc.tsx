import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ImagePicker } from '../components/Media';
import { PostList } from '../components/PostCard';
import { Avatar, Body, Empty, HumanBadge, Icon, Spinner } from '../components/common';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import type { Board, Comment, Media, Notification, Post, User } from '../lib/types';

/* --------------------------------------------------------------- profile */

export function ProfilePage() {
  const { username = '' } = useParams();
  const { user } = useApp();
  const [profile, setProfile] = useState<User | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [tab, setTab] = useState<'posts' | 'comments'>('posts');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .user(username)
      .then((data) => {
        setProfile(data.profile);
        setPosts(data.posts);
        setComments(data.comments);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : 'No such user.'));
  }, [username]);

  if (error) return <div className="card"><Empty emoji="🔍" title={error} /></div>;
  if (!profile) return <Spinner label="Loading profile…" />;

  const isSelf = user?.id === profile.id;

  return (
    <>
      <div className="board-banner">
        <div className="board-banner-top" style={{ background: profile.banner_color || profile.avatar_color }} />
        <div className="board-banner-body">
          <span className="board-icon" style={{ background: profile.avatar_color }}>
            {profile.avatar_emoji}
          </span>
          <div className="board-heading grow">
            <h1 className="row" style={{ gap: 8 }}>
              {profile.display_name}
              {/* Only real accounts carry a badge; personas carry nothing. */}
              <HumanBadge
                badge={profile.kind === 'human' ? { kind: 'human', label: 'human', title: 'A real person' } : null}
              />
            </h1>
            <span className="handle">
              u/{profile.username} · {formatScore(profile.karma.post)} post karma ·{' '}
              {formatScore(profile.karma.comment)} comment karma
            </span>
            {profile.bio ? <p className="small" style={{ marginBottom: 0 }}>{profile.bio}</p> : null}
          </div>
          {isSelf ? (
            <Link to="/settings" className="btn btn-outline btn-sm">
              {Icon.gear()} Edit profile
            </Link>
          ) : null}
        </div>
      </div>

      <div className="tabs">
        <button className={`tab${tab === 'posts' ? ' active' : ''}`} onClick={() => setTab('posts')}>
          Posts ({posts.length})
        </button>
        <button className={`tab${tab === 'comments' ? ' active' : ''}`} onClick={() => setTab('comments')}>
          Comments ({comments.length})
        </button>
      </div>

      {tab === 'posts' ? (
        posts.length ? (
          <PostList posts={posts} />
        ) : (
          <div className="card"><Empty emoji="📭" title="No posts yet" /></div>
        )
      ) : comments.length ? (
        <div className="stack">
          {comments.map((comment) => (
            <div className="card card-pad" key={comment.id}>
              <div className="tiny muted" style={{ marginBottom: 4 }}>
                <Link to={`/r/${comment.subreddit}`}>r/{comment.subreddit}</Link> ·{' '}
                {formatScore(comment.score)} points · {comment.age_label}
              </div>
              {comment.removed ? (
                <div className="removed-stub">[removed]</div>
              ) : (
                <Body text={comment.body} className="comment-body" />
              )}
              <Link className="tiny" to={`/r/${comment.subreddit}/comments/${comment.post_id}?comment=${comment.id}`}>
                view in thread →
              </Link>
            </div>
          ))}
        </div>
      ) : (
        <div className="card"><Empty emoji="🤐" title="No comments yet" /></div>
      )}
    </>
  );
}

/* ---------------------------------------------------------------- submit */

export function SubmitPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { user, notify } = useApp();
  const [boards, setBoards] = useState<Board[]>([]);
  const [board, setBoard] = useState(params.get('board') ?? '');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState<'text' | 'link' | 'image'>('text');
  const [linkUrl, setLinkUrl] = useState('');
  const [media, setMedia] = useState<Media | null>(null);
  const [nsfw, setNsfw] = useState(false);
  const [busy, setBusy] = useState(false);

  const activeBoard = boards.find((entry) => entry.name === board);
  const isPhotoBoard = activeBoard?.kind === 'photo';

  useEffect(() => {
    void api.boards.list().then((data) => {
      setBoards(data.boards);
      if (!board && data.boards.length) setBoard(data.boards[0].name);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A photo board only accepts image posts, so don't leave a stale tab selected.
  useEffect(() => {
    if (isPhotoBoard) setKind('image');
    else if (kind === 'image' && !media) setKind('text');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isPhotoBoard]);

  const submit = async () => {
    if (!user) {
      notify('Sign in or continue as a guest to post.', 'error');
      return;
    }
    setBusy(true);
    try {
      const { post } = await api.posts.create({
        subreddit: board,
        title,
        body,
        kind,
        link_url: linkUrl,
        media_id: media?.id ?? null,
        nsfw,
        generate_replies: true,
      });
      notify('Posted. People are already reading it.', 'success');
      navigate(`/r/${post.subreddit}/comments/${post.id}`);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not post that.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card card-pad">
      <h1 style={{ fontSize: 20, marginTop: 0 }}>Create a post</h1>

      <div className="field">
        <label htmlFor="submit-board">Board</label>
        <select id="submit-board" value={board} onChange={(event) => setBoard(event.target.value)}>
          {boards.map((entry) => (
            <option key={entry.id} value={entry.name}>
              r/{entry.name}
            </option>
          ))}
        </select>
      </div>

      {isPhotoBoard ? (
        <p className="small muted" style={{ marginTop: -4 }}>
          r/{board} is a photo board — every post is a picture.
        </p>
      ) : (
        <div className="tabs" style={{ marginBottom: 14 }}>
          <button className={`tab${kind === 'text' ? ' active' : ''}`} onClick={() => setKind('text')}>
            Text
          </button>
          <button className={`tab${kind === 'link' ? ' active' : ''}`} onClick={() => setKind('link')}>
            Link
          </button>
          <button className={`tab${kind === 'image' ? ' active' : ''}`} onClick={() => setKind('image')}>
            Image
          </button>
        </div>
      )}

      {kind === 'image' || isPhotoBoard ? (
        <div className="field">
          <label>Image</label>
          <ImagePicker
            board={board}
            media={media}
            onPicked={(picked) => {
              setMedia(picked);
              // The vision pass suggests titles; offer one rather than
              // making the user invent a caption for their own upload.
              if (!title && picked.caption) setTitle(picked.caption);
            }}
            onCleared={() => setMedia(null)}
          />
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="submit-title">Title</label>
        <input
          id="submit-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={300}
          placeholder="Say the thing"
        />
        <span className="hint">{title.length}/300</span>
      </div>

      {kind === 'link' ? (
        <div className="field">
          <label htmlFor="submit-link">URL</label>
          <input
            id="submit-link"
            value={linkUrl}
            onChange={(event) => setLinkUrl(event.target.value)}
            placeholder="https://…"
          />
        </div>
      ) : (
        <div className="field">
          <label htmlFor="submit-body">Body</label>
          <textarea
            id="submit-body"
            style={{ minHeight: 180 }}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="Optional. Markdown-ish: **bold**, *italic*, `code`, > quote"
          />
        </div>
      )}

      <label className="row small" style={{ gap: 8, marginBottom: 14 }}>
        <input type="checkbox" checked={nsfw} onChange={(event) => setNsfw(event.target.checked)} />
        Mark as NSFW
      </label>

      <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
        <button className="btn btn-ghost" onClick={() => navigate(-1)}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={busy || !title.trim() || !board || ((isPhotoBoard || kind === 'image') && !media)}
          onClick={() => void submit()}
        >
          {busy ? 'Posting…' : 'Post'}
        </button>
      </div>
      <p className="tiny faint" style={{ marginTop: 10 }}>
        Real posts get a friendlier reception than the simulated ones — but a bad take still sinks.
      </p>
    </div>
  );
}

/* ---------------------------------------------------------------- boards */

export function BoardsPage() {
  const { user, toggleSubscription } = useApp();
  const [boards, setBoards] = useState<Board[]>([]);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('subscribers');

  useEffect(() => {
    void api.boards.list(query, sort).then((data) => setBoards(data.boards));
  }, [query, sort]);

  return (
    <>
      <h1 style={{ fontSize: 22, marginTop: 0 }}>All boards</h1>
      <div className="tabs">
        <input
          style={{ maxWidth: 260 }}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter boards"
        />
        <span className="grow" />
        {['subscribers', 'new', 'active'].map((option) => (
          <button key={option} className={`tab${sort === option ? ' active' : ''}`} onClick={() => setSort(option)}>
            {option}
          </button>
        ))}
      </div>

      <div className="stack">
        {boards.map((board) => (
          <div className="card card-pad row" key={board.id} style={{ gap: 12 }}>
            <span className="sub-dot" style={{ background: board.color, width: 40, height: 40, fontSize: 19 }}>
              {board.icon}
            </span>
            <div className="grow" style={{ minWidth: 0 }}>
              <Link to={`/r/${board.name}`} style={{ fontWeight: 700 }}>
                r/{board.name}
              </Link>
              {board.nsfw ? <span className="flair tag-nsfw" style={{ marginLeft: 6 }}>NSFW</span> : null}
              {!board.is_official && board.creator_username ? (
                <span className="flair" style={{ marginLeft: 6 }}>
                  by u/{board.creator_username}
                </span>
              ) : null}
              <div className="small muted">{board.description}</div>
              <div className="tiny faint">
                {formatScore(board.subscribers)} members · {board.post_count} posts
              </div>
            </div>
            {user ? (
              <button
                className={`btn btn-sm ${board.subscribed ? 'btn-outline' : 'btn-primary'}`}
                onClick={() => void toggleSubscription(board.name, board.subscribed)}
              >
                {board.subscribed ? 'Joined' : 'Join'}
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- search */

export function SearchPage() {
  const [params] = useSearchParams();
  const query = params.get('q') ?? '';
  const [posts, setPosts] = useState<Post[]>([]);
  const [boards, setBoards] = useState<Board[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!query) return;
    setLoading(true);
    void api
      .search(query)
      .then((data) => {
        setPosts(data.posts);
        setBoards(data.boards);
      })
      .finally(() => setLoading(false));
  }, [query]);

  return (
    <>
      <h1 style={{ fontSize: 20, marginTop: 0 }}>
        Results for <em>{query}</em>
      </h1>
      {loading ? (
        <Spinner label="Searching…" />
      ) : (
        <>
          {boards.length ? (
            <div className="card card-pad" style={{ marginBottom: 12 }}>
              <p className="card-title">Boards</p>
              <div className="row wrap" style={{ gap: 8 }}>
                {boards.map((board) => (
                  <Link to={`/r/${board.name}`} key={board.id} className="chip">
                    {board.icon} r/{board.name}
                  </Link>
                ))}
              </div>
            </div>
          ) : null}
          {posts.length ? (
            <PostList posts={posts} />
          ) : (
            <div className="card"><Empty emoji="🔎" title="Nothing matched" hint="Try a different word." /></div>
          )}
        </>
      )}
    </>
  );
}

/* ----------------------------------------------------------------- inbox */

export function InboxPage() {
  const { refreshUnread } = useApp();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () =>
    void api.me
      .inbox()
      .then((data) => setNotifications(data.notifications))
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const markAll = async () => {
    await api.me.markAllRead();
    load();
    await refreshUnread();
  };

  if (loading) return <Spinner label="Loading your inbox…" />;

  return (
    <>
      <div className="row-between" style={{ marginBottom: 12 }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>Inbox</h1>
        <div className="row" style={{ gap: 8 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => void markAll()}>
            Mark all read
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={async () => {
              await api.me.clearInbox();
              load();
              await refreshUnread();
            }}
          >
            Clear
          </button>
        </div>
      </div>

      {notifications.length ? (
        <div className="stack">
          {notifications.map((entry) => (
            <Link
              key={entry._id}
              to={
                entry.post_id
                  ? `/r/${entry.subreddit}/comments/${entry.post_id}${entry.comment_id ? `?comment=${entry.comment_id}` : ''}`
                  : '#'
              }
              className="card card-pad"
              style={{ borderLeft: entry.read ? undefined : '3px solid var(--accent)' }}
            >
              <div className="row" style={{ gap: 8 }}>
                <Avatar size={22} emoji={entry.kind === 'award' ? '🏅' : '💬'} color="var(--surface-3)" />
                <div className="grow">
                  <div style={{ fontWeight: 700 }}>{entry.title}</div>
                  <div className="small muted">{entry.body}</div>
                  <div className="tiny faint">
                    r/{entry.subreddit} · {new Date(entry.at * 1000).toLocaleString()}
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card">
          <Empty emoji="📬" title="Nothing here yet" hint="Post or comment somewhere — replies land here." />
        </div>
      )}
    </>
  );
}

/* ----------------------------------------------------------------- saved */

export function SavedPage() {
  const { user } = useApp();
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    void api.me
      .savedPosts()
      .then((data) => setPosts(data.posts))
      .finally(() => setLoading(false));
  }, [user]);

  if (!user) {
    return (
      <div className="card">
        <Empty emoji="🔖" title="Sign in to save posts" hint="Guests can save too — continue as a guest from the login page." />
      </div>
    );
  }

  if (loading) return <Spinner label="Loading your saved posts…" />;

  return (
    <>
      <h1 style={{ fontSize: 22, marginTop: 0 }}>Saved</h1>
      {posts.length ? (
        <PostList
          posts={posts}
          onChanged={(updated) =>
            setPosts((current) =>
              updated.saved ? current.map((p) => (p.id === updated.id ? updated : p)) : current.filter((p) => p.id !== updated.id),
            )
          }
        />
      ) : (
        <div className="card">
          <Empty emoji="🔖" title="Nothing saved yet" hint="Hit “Save” on any post to read or reply to it later." />
        </div>
      )}
    </>
  );
}

/* -------------------------------------------------------------- not found */

export function NotFoundPage() {
  return (
    <div className="card">
      <Empty emoji="🫠" title="There doesn't seem to be anything here" hint="The page you wanted does not exist." />
    </div>
  );
}
