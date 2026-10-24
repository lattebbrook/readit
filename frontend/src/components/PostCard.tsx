import { useState, type MouseEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import type { Award, Post } from '../lib/types';
import { AwardPicker, AwardStrip } from './AwardPicker';
import { Avatar, Body, Dropdown, HumanBadge, Icon } from './common';
import { PostImage } from './Media';
import { VoteBox } from './VoteBox';

interface Props {
  post: Post;
  detail?: boolean;
  onChanged?: (post: Post) => void;
}

export function PostCard({ post, detail = false, onChanged }: Props) {
  const { user, notify } = useApp();
  const navigate = useNavigate();
  const [awards, setAwards] = useState<Award[]>(post.awards);
  const [showAwards, setShowAwards] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const [saved, setSaved] = useState(post.saved);
  const [savingBusy, setSavingBusy] = useState(false);

  const preferences = user?.preferences;
  const blurred = post.nsfw && (preferences?.blur_nsfw ?? true) && !revealed && !detail;
  const permalink = `/r/${post.subreddit}/comments/${post.id}`;

  // Reddit-style: the whole card opens the thread, except the vote arrows,
  // links, and buttons that already do their own thing.
  const handleCardClick = (event: MouseEvent<HTMLElement>) => {
    if (detail) return;
    const target = event.target as HTMLElement;
    if (target.closest('a, button, input, textarea, .votebox, .dropdown')) return;
    navigate(permalink);
  };

  const toggleSave = async () => {
    if (!user) {
      notify('Sign in or continue as a guest to save posts.', 'error');
      return;
    }
    const next = !saved;
    setSaved(next);
    setSavingBusy(true);
    try {
      if (next) await api.me.savePost(post.id);
      else await api.me.unsavePost(post.id);
      onChanged?.({ ...post, saved: next });
    } catch {
      setSaved(!next);
      notify('Could not save that post.', 'error');
    } finally {
      setSavingBusy(false);
    }
  };

  const share = async () => {
    try {
      const { url } = await api.share('post', post.id);
      const absolute = `${window.location.origin}${url}`;
      await navigator.clipboard?.writeText(absolute);
      notify('Link copied to clipboard.', 'success');
    } catch {
      notify('Could not copy that link.', 'error');
    }
  };

  const report = async () => {
    const reason = window.prompt('What is wrong with this post?');
    if (!reason) return;
    await api.report('post', post.id, reason);
    notify('Reported. The mods will take a look.', 'success');
  };

  const remove = async () => {
    if (!window.confirm('Delete this post? It stays in the thread as [deleted].')) return;
    const { post: updated } = await api.posts.remove(post.id);
    onChanged?.(updated);
    notify('Post deleted.', 'success');
  };

  return (
    <article className={`post${detail ? ' detail' : ''}`} onClick={handleCardClick}>
      <VoteBox
        kind="post"
        id={post.id}
        score={post.score}
        userVote={post.user_vote}
        onChange={(score) => onChanged?.({ ...post, score })}
      />

      <div className="post-main">
        <div className="post-meta">
          <Link to={`/r/${post.subreddit}`} className="row" style={{ gap: 5 }}>
            <span className="sub-dot" style={{ background: 'var(--surface-3)' }}>
              {post.subreddit.slice(0, 1).toLowerCase()}
            </span>
            r/{post.subreddit}
          </Link>
          <span className="dot" />
          <span>
            Posted by{' '}
            <Link to={`/u/${post.author}`} style={{ fontWeight: 400 }}>
              u/{post.author}
            </Link>
          </span>
          <HumanBadge badge={post.author_badge} show={preferences?.show_human_badges ?? true} />
          <span className="dot" />
          <span>{post.age_label}</span>
          {post.edited ? <span className="faint tiny">(edited)</span> : null}
          {awards.length ? <AwardStrip awards={awards} /> : null}
        </div>

        <div className={blurred ? 'nsfw-blur' : ''}>
          {detail ? (
            <h1 className="post-title">{post.title}</h1>
          ) : (
            <Link to={permalink} className="post-title" style={{ display: 'block' }}>
              {post.title}
            </Link>
          )}
        </div>

        <div className="row wrap" style={{ gap: 6, marginBottom: 6 }}>
          {post.flair ? <span className="flair">{post.flair}</span> : null}
          {post.nsfw ? <span className="flair tag-nsfw">NSFW</span> : null}
          {post.spoiler ? <span className="flair">spoiler</span> : null}
          {post.locked ? (
            <span className="flair tag-locked row" style={{ gap: 4 }}>
              {Icon.lock()} locked
            </span>
          ) : null}
          {post.stickied ? <span className="flair" style={{ color: 'var(--ok)' }}>📌 pinned</span> : null}
        </div>

        {post.kind === 'link' && post.link_url ? (
          <a
            className="link-chip"
            href={post.link_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {post.link_url} ↗
          </a>
        ) : null}

        {post.media ? <PostImage media={post.media} detail={detail} /> : null}

        {post.removed ? (
          <div className="removed-stub">
            [removed]
            <div className="removed-note">
              Removed by moderator{post.removed_by ? ` ${post.removed_by}` : ''}
              {post.removal_reason ? ` — ${post.removal_reason}` : ''}
            </div>
          </div>
        ) : post.deleted_by_author ? (
          <div className="removed-stub">[deleted by the person who wrote it]</div>
        ) : post.body ? (
          <div className={`post-body${detail ? ' full' : ' clipped'}${blurred ? ' nsfw-blur' : ''}`}>
            <Body text={post.body} />
          </div>
        ) : null}

        {blurred ? (
          <button className="btn btn-outline btn-sm" onClick={() => setRevealed(true)} style={{ marginTop: 8 }}>
            Show NSFW content
          </button>
        ) : null}

        <div className="post-actions">
          <Link to={permalink} className="action">
            {Icon.comment()} {formatScore(post.comment_count)} comments
          </Link>
          <button className="action" onClick={() => void share()}>
            {Icon.share()} Share
          </button>
          <button className="action" onClick={() => setShowAwards(true)}>
            {Icon.award()} Award
          </button>
          <button
            className="action"
            onClick={() => void toggleSave()}
            disabled={savingBusy}
            style={saved ? { color: 'var(--accent)' } : undefined}
          >
            {Icon.bookmark(15, saved)} {saved ? 'Saved' : 'Save'}
          </button>
          <Dropdown trigger={() => Icon.more()}>
            {(close) => (
              <>
                <button
                  className="dropdown-item"
                  onClick={() => {
                    close();
                    void report();
                  }}
                >
                  {Icon.flag()} Report
                </button>
                {post.is_own ? (
                  <button
                    className="dropdown-item"
                    onClick={() => {
                      close();
                      void remove();
                    }}
                  >
                    {Icon.trash()} Delete
                  </button>
                ) : null}
                <Link className="dropdown-item" to={`/u/${post.author}`} onClick={close}>
                  <Avatar size={16} emoji="👤" color="var(--surface-3)" /> View u/{post.author}
                </Link>
              </>
            )}
          </Dropdown>
        </div>
      </div>

      {showAwards ? (
        <AwardPicker
          kind="post"
          targetId={post.id}
          onClose={() => setShowAwards(false)}
          onGranted={setAwards}
        />
      ) : null}
    </article>
  );
}

export function PostList({
  posts,
  onChanged,
}: {
  posts: Post[];
  onChanged?: (post: Post) => void;
}) {
  return (
    <div className="post-list">
      {posts.map((post) => (
        <PostCard key={post.id} post={post} onChanged={onChanged} />
      ))}
    </div>
  );
}
