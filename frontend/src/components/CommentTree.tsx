import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import type { Award, Comment } from '../lib/types';
import { AwardPicker, AwardStrip } from './AwardPicker';
import { Body, Dropdown, HumanBadge, Icon, Spinner } from './common';
import { VoteBox } from './VoteBox';

interface NodeProps {
  comment: Comment;
  onReplied: (comment: Comment) => void;
  onChanged: (comment: Comment) => void;
  highlightId?: string | null;
  locked?: boolean;
}

function countDescendants(comment: Comment): number {
  return comment.replies.reduce((total, child) => total + 1 + countDescendants(child), 0);
}

function CommentNode({ comment, onReplied, onChanged, highlightId, locked }: NodeProps) {
  const { user, notify } = useApp();
  const [collapsed, setCollapsed] = useState(false);
  const [replying, setReplying] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [editDraft, setEditDraft] = useState(comment.body);
  const [busy, setBusy] = useState(false);
  const [summoning, setSummoning] = useState(false);
  const [showAwards, setShowAwards] = useState(false);
  const [awards, setAwards] = useState<Award[]>(comment.awards);

  const preferences = user?.preferences;
  const highlighted = highlightId === comment.id;

  const submitReply = async () => {
    if (!draft.trim()) return;
    if (!user) {
      notify('Sign in or continue as a guest to reply.', 'error');
      return;
    }
    setBusy(true);
    try {
      const { comment: created } = await api.posts.comment(comment.post_id, draft, comment.id);
      onReplied(created);
      setDraft('');
      setReplying(false);
      notify('Posted. Someone will be along shortly.', 'success');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Reply failed.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const submitEdit = async () => {
    setBusy(true);
    try {
      const { comment: updated } = await api.comments.edit(comment.id, editDraft);
      onChanged(updated);
      setEditing(false);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Edit failed.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm('Delete this comment? It stays as [deleted] so replies still make sense.'))
      return;
    const { comment: updated } = await api.comments.remove(comment.id);
    onChanged(updated);
  };

  const summonReplies = async () => {
    setSummoning(true);
    try {
      await api.comments.summonReplies(comment.id, 3);
      notify('Someone is typing…', 'success');
      onChanged({ ...comment });
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Nobody answered.', 'error');
    } finally {
      setSummoning(false);
    }
  };

  const share = async () => {
    const { url } = await api.share('comment', comment.id);
    await navigator.clipboard?.writeText(`${window.location.origin}${url}`);
    notify('Comment link copied.', 'success');
  };

  const descendants = countDescendants(comment);

  if (collapsed) {
    return (
      <div className="comment">
        <div className="comment-collapsed row" style={{ gap: 6 }}>
          <button className="collapse-btn" onClick={() => setCollapsed(false)} aria-label="Expand">
            [+]
          </button>
          <Link to={`/u/${comment.author}`} className="comment-author">
            u/{comment.author}
          </Link>
          <HumanBadge badge={comment.author_badge} show={preferences?.show_human_badges ?? true} />
          <span className="faint">
            {formatScore(comment.score)} points · {descendants} hidden
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="comment"
      id={`comment-${comment.id}`}
      style={
        highlighted
          ? { background: 'rgba(255,176,0,0.07)', borderRadius: 6, padding: '6px 8px' }
          : undefined
      }
    >
      <div className="comment-head">
        <button className="collapse-btn" onClick={() => setCollapsed(true)} aria-label="Collapse">
          [–]
        </button>
        <Link
          to={`/u/${comment.author}`}
          className={`comment-author${comment.is_op ? ' op' : ''}`}
        >
          u/{comment.author}
        </Link>
        <HumanBadge badge={comment.author_badge} show={preferences?.show_human_badges ?? true} />
        {comment.is_op ? <span className="op-tag">OP</span> : null}
        <span className="faint">
          {formatScore(comment.score)} point{comment.score === 1 ? '' : 's'}
        </span>
        <span className="dot" />
        <span className="faint">{comment.age_label}</span>
        {comment.edited ? <span className="faint tiny">(edited)</span> : null}
        {awards.length ? <AwardStrip awards={awards} /> : null}
      </div>

      {comment.removed ? (
        <div className="comment-body">
          <div className="removed-stub">[removed]</div>
          <div className="removed-note">
            Comment removed by moderator{comment.removed_by ? ` ${comment.removed_by}` : ''}
            {comment.removal_reason ? ` — ${comment.removal_reason}` : ''}
          </div>
        </div>
      ) : comment.deleted_by_author ? (
        <div className="comment-body">
          <div className="removed-stub">[deleted by the person who wrote it]</div>
        </div>
      ) : editing ? (
        <div className="composer">
          <textarea value={editDraft} onChange={(event) => setEditDraft(event.target.value)} />
          <div className="composer-actions">
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>
              Cancel
            </button>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void submitEdit()}>
              Save
            </button>
          </div>
        </div>
      ) : (
        <Body text={comment.body} className="comment-body" />
      )}

      <div className="comment-actions">
        <VoteBox
          kind="comment"
          id={comment.id}
          score={comment.score}
          userVote={comment.user_vote}
          layout="inline"
        />
        {!locked ? (
          <button className="action" onClick={() => setReplying((value) => !value)}>
            Reply
          </button>
        ) : null}
        <button className="action" onClick={() => void share()}>
          Share
        </button>
        <button className="action" onClick={() => setShowAwards(true)}>
          Award
        </button>
        {!locked ? (
          <button className="action" onClick={() => void summonReplies()} disabled={summoning}>
            {summoning ? <Spinner /> : <>{Icon.spark()} Poke</>}
          </button>
        ) : null}
        {comment.is_own && !comment.deleted_by_author ? (
          <Dropdown trigger={() => Icon.more()}>
            {(close) => (
              <>
                <button
                  className="dropdown-item"
                  onClick={() => {
                    close();
                    setEditing(true);
                  }}
                >
                  Edit
                </button>
                <button
                  className="dropdown-item"
                  onClick={() => {
                    close();
                    void remove();
                  }}
                >
                  {Icon.trash()} Delete
                </button>
              </>
            )}
          </Dropdown>
        ) : null}
      </div>

      {replying ? (
        <div className="composer">
          <textarea
            autoFocus
            value={draft}
            placeholder={`Reply to u/${comment.author}…`}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="composer-actions">
            <button className="btn btn-ghost btn-sm" onClick={() => setReplying(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary btn-sm"
              disabled={busy || !draft.trim()}
              onClick={() => void submitReply()}
            >
              {busy ? 'Posting…' : 'Reply'}
            </button>
          </div>
        </div>
      ) : null}

      {comment.replies.length ? (
        <div className="comment-children">
          {comment.replies.map((child) => (
            <CommentNode
              key={child.id}
              comment={child}
              onReplied={onReplied}
              onChanged={onChanged}
              highlightId={highlightId}
              locked={locked}
            />
          ))}
        </div>
      ) : null}

      {comment.hidden_replies > 0 ? (
        <div className="comment-children">
          <span className="small" style={{ color: 'var(--link)' }}>
            continue this thread → {comment.hidden_replies} more
          </span>
        </div>
      ) : null}

      {showAwards ? (
        <AwardPicker
          kind="comment"
          targetId={comment.id}
          onClose={() => setShowAwards(false)}
          onGranted={setAwards}
        />
      ) : null}
    </div>
  );
}

export function CommentTree({
  comments,
  onReplied,
  onChanged,
  highlightId,
  locked,
}: {
  comments: Comment[];
  onReplied: (comment: Comment) => void;
  onChanged: (comment: Comment) => void;
  highlightId?: string | null;
  locked?: boolean;
}) {
  return (
    <div className="comments">
      {comments.map((comment) => (
        <CommentNode
          key={comment.id}
          comment={comment}
          onReplied={onReplied}
          onChanged={onChanged}
          highlightId={highlightId}
          locked={locked}
        />
      ))}
    </div>
  );
}
