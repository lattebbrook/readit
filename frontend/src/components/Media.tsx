import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { formatScore } from '../lib/format';
import { useApp } from '../lib/store';
import type { Media, Post } from '../lib/types';
import { HumanBadge, Icon, Spinner } from './common';

/* --------------------------------------------------------------- lightbox */

export function Lightbox({ media, onClose }: { media: Media; onClose: () => void }) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handler);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  return (
    <div className="lightbox" onClick={onClose} role="presentation">
      <img src={media.url} alt={media.caption || 'Full size image'} />
    </div>
  );
}

/* ------------------------------------------------------------ post images */

export function PostImage({ media, detail = false }: { media: Media; detail?: boolean }) {
  const { user } = useApp();
  const [zoomed, setZoomed] = useState(false);
  const [revealed, setRevealed] = useState(false);

  const blurred = media.nsfw && (user?.preferences?.blur_nsfw ?? true) && !revealed;

  return (
    <>
      <img
        className={`post-image${detail ? ' clickable' : ''}${blurred ? ' nsfw-blur' : ''}`}
        src={detail ? media.url : media.thumb_url}
        alt={media.caption || ''}
        loading="lazy"
        // Reserving the intrinsic ratio stops the page jumping as images load.
        width={media.width || undefined}
        height={media.height || undefined}
        onClick={(event) => {
          if (!detail) return;
          event.stopPropagation();
          if (blurred) setRevealed(true);
          else setZoomed(true);
        }}
      />
      {detail && media.caption ? <div className="media-caption">{media.caption}</div> : null}
      {detail && media.source_page ? (
        <a
          className="media-source"
          href={media.source_page}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(event) => event.stopPropagation()}
        >
          source: {media.source_site || media.source_page} ↗
        </a>
      ) : null}
      {zoomed ? <Lightbox media={media} onClose={() => setZoomed(false)} /> : null}
    </>
  );
}

/* -------------------------------------------------------------- photo grid */

export function PhotoGrid({ posts }: { posts: Post[] }) {
  const { user } = useApp();
  const blurNsfw = user?.preferences?.blur_nsfw ?? true;

  return (
    <div className="photo-grid">
      {posts.map((post) => (
        <Link
          key={post.id}
          to={`/r/${post.subreddit}/comments/${post.id}`}
          className="photo-card"
          style={{ display: 'block', color: 'inherit' }}
        >
          {post.media ? (
            <img
              src={post.media.thumb_url}
              alt={post.media.caption || post.title}
              loading="lazy"
              className={post.media.nsfw && blurNsfw ? 'nsfw-blur' : ''}
              style={{ aspectRatio: post.media.aspect_ratio || undefined }}
            />
          ) : null}
          <div className="photo-card-body">
            <div className="photo-card-title">{post.title}</div>
            <div className="photo-card-meta">
              <span>{Icon.up(12)}</span>
              <span>{formatScore(post.score)}</span>
              <span>· {formatScore(post.comment_count)} comments</span>
            </div>
            <div className="photo-card-meta" style={{ marginTop: 4 }}>
              <span>u/{post.author}</span>
              <HumanBadge
                badge={post.author_badge}
                show={user?.preferences?.show_human_badges ?? true}
              />
              <span>· {post.age_label}</span>
            </div>
          </div>
        </Link>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------- image picker */

/**
 * One control covering every way an image gets in: file picker, paste,
 * drag-and-drop, or a pasted URL the backend fetches itself.
 */
export function ImagePicker({
  board,
  media,
  onPicked,
  onCleared,
}: {
  board: string;
  media: Media | null;
  onPicked: (media: Media) => void;
  onCleared: () => void;
}) {
  const { notify } = useApp();
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [urlDraft, setUrlDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const send = useCallback(
    async (file: File | Blob) => {
      setBusy(true);
      try {
        const { media: uploaded } = await api.media.upload(file, board);
        onPicked(uploaded);
      } catch (error) {
        notify(error instanceof Error ? error.message : 'Upload failed.', 'error');
      } finally {
        setBusy(false);
      }
    },
    [board, onPicked, notify],
  );

  const fetchUrl = async () => {
    if (!urlDraft.trim()) return;
    setBusy(true);
    try {
      const { media: fetched } = await api.media.fromUrl(urlDraft.trim(), board);
      onPicked(fetched);
      setUrlDraft('');
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not fetch that image.', 'error');
    } finally {
      setBusy(false);
    }
  };

  // Paste anywhere on the page while composing. Browsers put a real image on
  // the clipboard for a copied picture, and a URL string for a copied link.
  useEffect(() => {
    if (media) return;
    const onPaste = (event: ClipboardEvent) => {
      const items = Array.from(event.clipboardData?.items ?? []);
      const imageItem = items.find((item) => item.type.startsWith('image/'));
      if (imageItem) {
        const file = imageItem.getAsFile();
        if (file) {
          event.preventDefault();
          void send(file);
        }
        return;
      }
      const text = event.clipboardData?.getData('text') ?? '';
      if (/^https?:\/\/\S+$/i.test(text.trim())) setUrlDraft(text.trim());
    };
    document.addEventListener('paste', onPaste);
    return () => document.removeEventListener('paste', onPaste);
  }, [media, send]);

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);

    const file = event.dataTransfer.files?.[0];
    if (file?.type.startsWith('image/')) {
      void send(file);
      return;
    }
    // Dragging an image between browser tabs delivers a URL, not a file.
    const dropped =
      event.dataTransfer.getData('text/uri-list') || event.dataTransfer.getData('text/plain');
    if (dropped && /^https?:\/\//i.test(dropped)) {
      setUrlDraft(dropped);
      void api.media
        .fromUrl(dropped, board)
        .then(({ media: fetched }) => onPicked(fetched))
        .catch((error) =>
          notify(error instanceof Error ? error.message : 'Could not fetch that image.', 'error'),
        );
    }
  };

  if (media) {
    return (
      <div className="dropzone has-image">
        <img className="dropzone-preview" src={media.url} alt={media.caption || 'Selected image'} />
        <div className="row-between" style={{ marginTop: 8 }}>
          <span className="analysis-chip">
            {media.analysis_state === 'done' ? (
              <>✓ described{media.caption ? ` — “${media.caption}”` : ''}</>
            ) : media.analysis_state === 'failed' ? (
              <span style={{ color: 'var(--warn)' }}>
                no description (check the vision role in Admin)
              </span>
            ) : (
              <>
                <Spinner /> looking at it…
              </>
            )}
          </span>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onCleared}>
            Remove
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div
        className={`dropzone${dragging ? ' dragging' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click();
        }}
      >
        {busy ? (
          <Spinner label="Uploading…" />
        ) : (
          <>
            <div style={{ fontSize: 26 }}>🖼️</div>
            <div style={{ fontWeight: 700, marginTop: 6 }}>
              Drop an image, paste it, or click to browse
            </div>
            <div className="tiny faint" style={{ marginTop: 4 }}>
              Drag straight from another tab, or ⌘V a copied picture
            </div>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void send(file);
            event.target.value = '';
          }}
        />
      </div>

      <div className="row" style={{ gap: 8, marginTop: 8 }}>
        <input
          value={urlDraft}
          onChange={(event) => setUrlDraft(event.target.value)}
          placeholder="…or paste an image link"
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void fetchUrl();
            }
          }}
        />
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={busy || !urlDraft.trim()}
          onClick={() => void fetchUrl()}
        >
          Fetch
        </button>
      </div>
    </>
  );
}
