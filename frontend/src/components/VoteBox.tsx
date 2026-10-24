import { useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import { Icon } from './common';

interface Props {
  kind: 'post' | 'comment';
  id: string;
  score: number;
  userVote: number;
  layout?: 'column' | 'inline';
  onChange?: (score: number, direction: number) => void;
}

/**
 * Optimistic voting: the arrow flips instantly and reconciles with the server's
 * authoritative score, which also moves on its own as the simulated crowd votes.
 */
export function VoteBox({ kind, id, score, userVote, layout = 'column', onChange }: Props) {
  const { user, notify } = useApp();
  const [localScore, setLocalScore] = useState(score);
  const [localVote, setLocalVote] = useState(userVote);
  const [busy, setBusy] = useState(false);
  const dirty = useRef(false);

  // Scores keep moving on the server as the simulated crowd votes, so adopt
  // incoming values — unless this user has already touched the arrows, whose
  // own vote must not be stomped by a stale poll.
  useEffect(() => {
    if (!dirty.current) setLocalScore(score);
  }, [score]);

  useEffect(() => {
    if (!dirty.current) setLocalVote(userVote);
  }, [userVote]);

  const cast = async (direction: number) => {
    if (!user) {
      notify('Sign in or continue as a guest to vote.', 'error');
      return;
    }
    const next = localVote === direction ? 0 : direction;
    const delta = next - localVote;
    dirty.current = true;
    setLocalVote(next);
    setLocalScore((current) => current + delta);
    setBusy(true);
    try {
      const result = await api.vote(kind, id, direction);
      setLocalScore(result.score);
      setLocalVote(result.direction);
      onChange?.(result.score, result.direction);
    } catch {
      setLocalVote(localVote);
      setLocalScore((current) => current - delta);
      notify('That vote did not go through.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const scoreClass = localVote === 1 ? 'up' : localVote === -1 ? 'down' : '';

  return (
    <div className={`votebox${layout === 'inline' ? ' inline' : ''}`}>
      <button
        className={`vote-btn up${localVote === 1 ? ' active' : ''}`}
        onClick={() => void cast(1)}
        aria-label="Upvote"
        aria-pressed={localVote === 1}
      >
        {Icon.up(layout === 'inline' ? 15 : 18)}
      </button>
      <span className={`vote-score ${scoreClass}`} title={`${localScore} points`}>
        {busy ? '·' : formatScore(Math.round(localScore))}
      </span>
      <button
        className={`vote-btn down${localVote === -1 ? ' active' : ''}`}
        onClick={() => void cast(-1)}
        aria-label="Downvote"
        aria-pressed={localVote === -1}
      >
        {Icon.down(layout === 'inline' ? 15 : 18)}
      </button>
    </div>
  );
}
