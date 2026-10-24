import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { CommentTree } from '../components/CommentTree';
import { PostCard } from '../components/PostCard';
import { Empty, Icon, Spinner } from '../components/common';
import { useRail } from '../components/Layout';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import type { Board, Comment, Post } from '../lib/types';

const SORTS = ['best', 'top', 'new', 'controversial', 'old', 'qa'];

const LOADING_LINES = [
  'waking people up…',
  'someone is typing…',
  'three people started replying at once…',
  'a regular just opened this thread…',
  'somebody is drafting a very long comment…',
  'the argument is warming up…',
];

function ThreadRail({ board, post }: { board: Board | null; post: Post | null }) {
  if (!board) return null;
  return (
    <>
      <div className="card card-pad">
        <div className="row" style={{ gap: 8, marginBottom: 8 }}>
          <span className="sub-dot" style={{ background: board.color, width: 28, height: 28, fontSize: 14 }}>
            {board.icon}
          </span>
          <Link to={`/r/${board.name}`} style={{ fontWeight: 700 }}>
            r/{board.name}
          </Link>
        </div>
        <p className="small muted">{board.description}</p>
        <div className="divider" />
        <dl className="kv">
          <dt>Members</dt>
          <dd>{formatScore(board.subscribers)}</dd>
          <dt>Here now</dt>
          <dd style={{ color: 'var(--ok)' }}>{formatScore(board.members_online)}</dd>
        </dl>
      </div>

      {post ? (
        <div className="card card-pad">
          <p className="card-title">This thread</p>
          <dl className="kv">
            <dt>Score</dt>
            <dd>{formatScore(post.score)}</dd>
            <dt>Upvote ratio</dt>
            <dd>
              {post.ups + post.downs > 0
                ? `${Math.round((post.ups / (post.ups + post.downs)) * 100)}%`
                : '—'}
            </dd>
            <dt>Comments</dt>
            <dd>{formatScore(post.comment_count)}</dd>
            <dt>Views</dt>
            <dd>{formatScore(post.view_count)}</dd>
          </dl>
        </div>
      ) : null}
    </>
  );
}

/** Replace a comment anywhere in the tree, or splice a new reply under its parent. */
function updateTree(nodes: Comment[], updated: Comment): Comment[] {
  return nodes.map((node) =>
    node.id === updated.id
      ? { ...updated, replies: node.replies }
      : { ...node, replies: updateTree(node.replies, updated) },
  );
}

function insertReply(nodes: Comment[], reply: Comment): Comment[] {
  return nodes.map((node) =>
    node.id === reply.parent_id
      ? { ...node, replies: [reply, ...node.replies] }
      : { ...node, replies: insertReply(node.replies, reply) },
  );
}

export function ThreadPage() {
  const { postId = '' } = useParams();
  const [params] = useSearchParams();
  const highlightId = params.get('comment');
  const { user, notify } = useApp();

  const [post, setPost] = useState<Post | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [comments, setComments] = useState<Comment[]>([]);
  const [sort, setSort] = useState('best');
  const [loading, setLoading] = useState(true);
  const [summoning, setSummoning] = useState(false);
  const [draft, setDraft] = useState('');
  const [posting, setPosting] = useState(false);
  const [line, setLine] = useState(LOADING_LINES[0]);
  const [error, setError] = useState<string | null>(null);
  const lastSeen = useRef(0);

  useRail(<ThreadRail board={board} post={post} />, [board, post]);

  // Cycle the "who's typing" line while the first batch is being written.
  useEffect(() => {
    if (!loading && !summoning) return;
    const timer = setInterval(
      () => setLine(LOADING_LINES[Math.floor(Math.random() * LOADING_LINES.length)]),
      2600,
    );
    return () => clearInterval(timer);
  }, [loading, summoning]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.posts.get(postId, sort, true);
      setPost(data.post);
      setBoard(data.board);
      setComments(data.comments);
      lastSeen.current = data.server_time;
      if (data.generated > 0) {
        notify(`${data.generated} people showed up.`, 'success');
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not open that thread.');
    } finally {
      setLoading(false);
    }
  }, [postId, sort, notify]);

  useEffect(() => {
    void load();
  }, [load]);

  // Background growth: latecomers, new replies, moderator removals.
  useEffect(() => {
    if (!(user?.preferences?.live_updates ?? true)) return;
    if (loading) return;
    const timer = setInterval(async () => {
      try {
        const data = await api.posts.updates(postId, lastSeen.current, sort);
        lastSeen.current = data.server_time;
        setPost(data.post);
        if (data.changed && data.comments) {
          setComments(data.comments);
          if (data.new_comments > 0) {
            notify(
              `${data.new_comments} new ${data.new_comments === 1 ? 'reply' : 'replies'}.`,
              'info',
            );
          }
        }
      } catch {
        /* transient */
      }
    }, 15_000);
    return () => clearInterval(timer);
  }, [postId, sort, loading, user?.preferences?.live_updates, notify]);

  useEffect(() => {
    if (!highlightId || loading) return;
    document.getElementById(`comment-${highlightId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [highlightId, loading]);

  const summonMore = async () => {
    setSummoning(true);
    try {
      const data = await api.posts.generate(postId, undefined, undefined);
      setComments(data.comments);
      setPost(data.post);
      notify(`${data.created} more comments landed.`, 'success');
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : 'Nobody replied.', 'error');
    } finally {
      setSummoning(false);
    }
  };

  const submitComment = async () => {
    if (!draft.trim()) return;
    if (!user) {
      notify('Sign in or continue as a guest to comment.', 'error');
      return;
    }
    setPosting(true);
    try {
      const { comment } = await api.posts.comment(postId, draft);
      setComments((current) => [comment, ...current]);
      setDraft('');
      notify('Posted. Give it a moment — someone always answers.', 'success');
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : 'Comment failed.', 'error');
    } finally {
      setPosting(false);
    }
  };

  if (error) {
    return (
      <div className="card">
        <Empty emoji="🕳️" title={error} />
      </div>
    );
  }

  if (loading && !post) {
    return (
      <div className="card card-pad">
        <div className="row" style={{ gap: 10 }}>
          <Spinner />
          <span className="muted pulse">{line}</span>
        </div>
        <p className="tiny faint" style={{ marginTop: 10 }}>
          The discussion for this thread is being written right now.
        </p>
      </div>
    );
  }

  return (
    <>
      {post ? (
        <PostCard post={post} detail onChanged={setPost} />
      ) : null}

      <div className="card card-pad" style={{ marginTop: 10 }}>
        {post?.locked ? (
          <div className="row" style={{ gap: 8, color: 'var(--warn)' }}>
            {Icon.lock()}
            <span className="small">
              This thread is locked. Existing comments stay up; nobody can add new ones.
            </span>
          </div>
        ) : (
          <div className="composer" style={{ margin: 0 }}>
            <label className="tiny muted" htmlFor="thread-composer">
              Comment as{' '}
              <strong style={{ color: 'var(--link)' }}>{user ? `u/${user.username}` : 'a guest'}</strong>
            </label>
            <textarea
              id="thread-composer"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="What are your thoughts?"
            />
            <div className="composer-actions">
              <button
                className="btn btn-primary btn-sm"
                disabled={posting || !draft.trim()}
                onClick={() => void submitComment()}
              >
                {posting ? 'Posting…' : 'Comment'}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="tabs" style={{ marginTop: 10 }}>
        <span className="small muted" style={{ marginRight: 6 }}>
          Sort by
        </span>
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
        {!post?.locked ? (
          <button className="btn btn-ghost btn-sm" onClick={() => void summonMore()} disabled={summoning}>
            {summoning ? <Spinner label={line} /> : <>{Icon.spark()} more discussion</>}
          </button>
        ) : null}
      </div>

      {comments.length ? (
        <CommentTree
          comments={comments}
          locked={post?.locked}
          highlightId={highlightId}
          onReplied={(reply) => setComments((current) => insertReply(current, reply))}
          onChanged={(updated) => setComments((current) => updateTree(current, updated))}
        />
      ) : (
        <div className="card" style={{ marginTop: 10 }}>
          <Empty
            emoji="🦗"
            title="No comments yet"
            hint="Press “more discussion” to bring people in, or say something first."
          />
        </div>
      )}
    </>
  );
}
