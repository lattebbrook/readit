import { useState } from 'react';
import { api } from '../lib/api';
import { useApp } from '../lib/store';
import type { Board } from '../lib/types';
import { ChipInput, Modal, Slider, Switch } from './common';

const DENSITIES = ['sparse', 'normal', 'busy', 'chaotic'];

/** Knobs a board may override; null means "inherit the site default". */
const OVERRIDE_KNOBS: { key: string; label: string; hint: string }[] = [
  { key: 'humor', label: 'Humour', hint: 'How much of the board is jokes' },
  { key: 'toxicity', label: 'Meanness', hint: 'How harsh people are with each other' },
  { key: 'argument_rate', label: 'Arguments', hint: 'How often threads turn into fights' },
  { key: 'wholesomeness', label: 'Warmth', hint: 'Kindness, encouragement, sincerity' },
  { key: 'shitpost_rate', label: 'Shitposting', hint: 'Low-effort nonsense' },
  { key: 'expertise', label: 'Expertise', hint: 'How many people actually know things' },
  { key: 'moderation_strictness', label: 'Mod strictness', hint: 'How eagerly mods step in' },
  { key: 'removal_rate', label: 'Removal rate', hint: 'How much gets taken down' },
];

function OverrideSliders({
  overrides,
  onChange,
}: {
  overrides: Record<string, number | string | null>;
  onChange: (overrides: Record<string, number | string | null>) => void;
}) {
  return (
    <div className="stack" style={{ gap: 4 }}>
      {OVERRIDE_KNOBS.map((knob) => {
        const value = overrides[knob.key];
        const active = value !== null && value !== undefined;
        return (
          <div className="field-row" key={knob.key}>
            <div className="grow">
              <div className="label small">{knob.label}</div>
              <div className="hint tiny">{knob.hint}</div>
            </div>
            <div style={{ width: 170 }}>
              {active ? (
                <Slider
                  value={Number(value)}
                  onChange={(next) => onChange({ ...overrides, [knob.key]: next })}
                />
              ) : (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onChange({ ...overrides, [knob.key]: 0.5 })}
                >
                  inherit — override
                </button>
              )}
            </div>
            {active ? (
              <button
                className="btn-ghost tiny"
                onClick={() => onChange({ ...overrides, [knob.key]: null })}
                title="Go back to inheriting the site default"
              >
                reset
              </button>
            ) : null}
          </div>
        );
      })}

      <div className="field-row">
        <div className="grow">
          <div className="label small">Comment density</div>
          <div className="hint tiny">How busy new threads get</div>
        </div>
        <select
          style={{ width: 170 }}
          value={(overrides.comment_density as string) ?? ''}
          onChange={(event) =>
            onChange({ ...overrides, comment_density: event.target.value || null })
          }
        >
          <option value="">inherit</option>
          {DENSITIES.map((density) => (
            <option key={density} value={density}>
              {density}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

export function CreateBoardModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (board: Board) => void;
}) {
  const { user, notify } = useApp();
  const [name, setName] = useState('');
  const [kind, setKind] = useState<'text' | 'photo'>('text');
  const [description, setDescription] = useState('');
  const [prompt, setPrompt] = useState('');
  const [overrideGlobal, setOverrideGlobal] = useState(false);
  const [nsfw, setNsfw] = useState(false);
  const [rules, setRules] = useState<string[]>([]);
  const [topics, setTopics] = useState<string[]>([]);
  const [overrides, setOverrides] = useState<Record<string, number | string | null>>({});
  const [autofill, setAutofill] = useState(true);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!user) {
      notify('Sign in or continue as a guest to create a board.', 'error');
      return;
    }
    setBusy(true);
    try {
      const { board } = await api.boards.create({
        name,
        kind,
        description,
        custom_prompt: prompt,
        override_global: overrideGlobal,
        nsfw,
        rules,
        topics,
        overrides,
        autofill,
        generate_metadata: !description,
      });
      notify(
        kind === 'photo'
          ? `r/${board.name} created — post a picture to get it going.`
          : autofill
            ? `r/${board.name} created — filling it with people…`
            : `r/${board.name} created.`,
        'success',
      );
      onCreated(board);
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not create that board.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Create a board"
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || name.length < 3} onClick={() => void create()}>
            {busy ? 'Creating…' : 'Create board'}
          </button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="board-name">Name</label>
        <div className="row">
          <span className="muted">r/</span>
          <input
            id="board-name"
            value={name}
            onChange={(event) => setName(event.target.value.replace(/[^A-Za-z0-9_]/g, ''))}
            placeholder="lateNightThoughts"
            maxLength={21}
          />
        </div>
        <span className="hint">3–21 characters. Letters, numbers and underscores.</span>
      </div>

      <div className="field">
        <label>Board type</label>
        <div className="row" style={{ gap: 6 }}>
          <button
            type="button"
            className={`btn btn-sm ${kind === 'text' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setKind('text')}
          >
            💬 Discussion
          </button>
          <button
            type="button"
            className={`btn btn-sm ${kind === 'photo' ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setKind('photo')}
          >
            🖼️ Photos
          </button>
        </div>
        <span className="hint">
          {kind === 'photo'
            ? 'Every post is an image, shown in a grid. You supply the pictures; the regulars supply the argument.'
            : 'Text and link posts, written by the board’s regulars.'}
        </span>
      </div>

      <div className="field">
        <label htmlFor="board-desc">Description</label>
        <input
          id="board-desc"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Leave blank and one will be written for you"
        />
      </div>

      <div className="field">
        <label htmlFor="board-prompt">Board instruction</label>
        <textarea
          id="board-prompt"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="Describe who hangs out here and how they talk. e.g. 'Everyone is a medieval peasant reacting to modern technology. Nobody breaks character. Arguments are about crop yields.'"
        />
        <span className="hint">
          This steers every post and comment generated in the board.
        </span>
      </div>

      <div className="field-row">
        <div className="grow">
          <div className="label">Replace the site prompt entirely</div>
          <div className="hint">
            On: your instruction is the only character guidance. Off: it layers on top of the site's.
          </div>
        </div>
        <Switch checked={overrideGlobal} onChange={setOverrideGlobal} label="Override global prompt" />
      </div>

      <div className="field-row">
        <div className="grow">
          <div className="label">NSFW / adult board</div>
          <div className="hint">Hidden unless a reader opts in from their settings.</div>
        </div>
        <Switch checked={nsfw} onChange={setNsfw} label="NSFW board" />
      </div>

      {/* A photo board cannot be pre-filled — nobody has an image to post yet. */}
      {kind === 'photo' ? null : (
        <div className="field-row">
          <div className="grow">
            <div className="label">Populate it now</div>
            <div className="hint">Write an opening batch of posts and one busy thread.</div>
          </div>
          <Switch checked={autofill} onChange={setAutofill} label="Populate now" />
        </div>
      )}

      <div className="field">
        <label>Rules</label>
        <ChipInput values={rules} onChange={setRules} placeholder="Add a rule and press Enter" />
      </div>

      <div className="field">
        <label>Recurring topics</label>
        <ChipInput values={topics} onChange={setTopics} placeholder="Add a topic and press Enter" />
      </div>

      <details>
        <summary className="card-title" style={{ cursor: 'pointer' }}>
          Advanced — board personality overrides
        </summary>
        <div style={{ marginTop: 10 }}>
          <OverrideSliders overrides={overrides} onChange={setOverrides} />
        </div>
      </details>
    </Modal>
  );
}

export function BoardSettingsModal({
  board,
  onClose,
  onSaved,
}: {
  board: Board;
  onClose: () => void;
  onSaved: (board: Board) => void;
}) {
  const { user, notify, setUser } = useApp();
  const [draft, setDraft] = useState({
    title: board.title,
    description: board.description,
    sidebar: board.sidebar,
    custom_prompt: board.custom_prompt ?? '',
    override_global: board.override_global ?? false,
    nsfw: board.nsfw,
    rules: board.rules,
    topics: board.topics,
    icon: board.icon,
    color: board.color,
    allow_user_posts: board.allow_user_posts,
    moderation_enabled: board.moderation_enabled,
    activity_level: board.activity_level ?? 1,
  });
  const [overrides, setOverrides] = useState<Record<string, number | string | null>>(
    board.overrides ?? {},
  );
  const [personalPrompt, setPersonalPrompt] = useState(board.personal_prompt ?? '');
  const [busy, setBusy] = useState(false);

  const blocked = (user?.banned_subreddits ?? []).includes(board.name);

  const save = async () => {
    setBusy(true);
    try {
      if (personalPrompt !== (board.personal_prompt ?? '')) {
        await api.boards.setPersonalPrompt(board.name, personalPrompt);
      }
      if (board.can_edit) {
        const { board: updated } = await api.boards.update(board.name, { ...draft, overrides });
        onSaved(updated);
      } else {
        onSaved({ ...board, personal_prompt: personalPrompt });
      }
      notify('Board settings saved.', 'success');
      onClose();
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Save failed.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const toggleBlock = async () => {
    const { user: updated } = blocked
      ? await api.me.unblockBoard(board.name)
      : await api.me.blockBoard(board.name);
    setUser(updated);
    notify(blocked ? `r/${board.name} unblocked.` : `r/${board.name} hidden from your feeds.`, 'success');
    if (!blocked) onClose();
  };

  const removeBoard = async () => {
    if (!window.confirm(`Delete r/${board.name} and everything in it? This cannot be undone.`)) return;
    await api.boards.remove(board.name);
    notify(`r/${board.name} deleted.`, 'success');
    window.location.href = '/';
  };

  return (
    <Modal
      title={`r/${board.name} settings`}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="personal-prompt">Your private steer for this board</label>
        <textarea
          id="personal-prompt"
          value={personalPrompt}
          onChange={(event) => setPersonalPrompt(event.target.value)}
          placeholder="Only affects what gets generated for you. e.g. 'lean technical, less meme'"
        />
        <span className="hint">
          Anyone can set this, even on boards they don't own. Nobody else sees the difference.
        </span>
      </div>

      <div className="field-row">
        <div className="grow">
          <div className="label">Hide this board from me</div>
          <div className="hint">It disappears from your feeds and search.</div>
        </div>
        <button className={`btn btn-sm ${blocked ? 'btn-outline' : 'btn-ghost'}`} onClick={() => void toggleBlock()}>
          {blocked ? 'Unhide' : 'Hide'}
        </button>
      </div>

      {!board.can_edit ? (
        <p className="muted small" style={{ marginTop: 16 }}>
          Only u/{board.creator_username ?? 'the creator'} can change how this board behaves for
          everyone. Your private steer above is yours alone.
        </p>
      ) : (
        <>
          <div className="divider" />

          <div className="field">
            <label htmlFor="edit-title">Title</label>
            <input
              id="edit-title"
              value={draft.title}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
            />
          </div>

          <div className="field">
            <label htmlFor="edit-desc">Description</label>
            <input
              id="edit-desc"
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            />
          </div>

          <div className="field">
            <label htmlFor="edit-sidebar">Sidebar text</label>
            <textarea
              id="edit-sidebar"
              value={draft.sidebar}
              onChange={(event) => setDraft({ ...draft, sidebar: event.target.value })}
            />
          </div>

          <div className="field">
            <label htmlFor="edit-prompt">Board instruction</label>
            <textarea
              id="edit-prompt"
              value={draft.custom_prompt}
              onChange={(event) => setDraft({ ...draft, custom_prompt: event.target.value })}
            />
            <span className="hint">Steers everything generated in this board.</span>
          </div>

          <div className="field-row">
            <div className="grow">
              <div className="label">Replace the site prompt entirely</div>
            </div>
            <Switch
              checked={draft.override_global}
              onChange={(value) => setDraft({ ...draft, override_global: value })}
              label="Override global prompt"
            />
          </div>

          <div className="field-row">
            <div className="grow">
              <div className="label">NSFW board</div>
            </div>
            <Switch
              checked={draft.nsfw}
              onChange={(value) => setDraft({ ...draft, nsfw: value })}
              label="NSFW"
            />
          </div>

          <div className="field-row">
            <div className="grow">
              <div className="label">Let people post here</div>
            </div>
            <Switch
              checked={draft.allow_user_posts}
              onChange={(value) => setDraft({ ...draft, allow_user_posts: value })}
              label="Allow user posts"
            />
          </div>

          <div className="field-row">
            <div className="grow">
              <div className="label">Moderation</div>
              <div className="hint">Off means nothing is ever removed here.</div>
            </div>
            <Switch
              checked={draft.moderation_enabled}
              onChange={(value) => setDraft({ ...draft, moderation_enabled: value })}
              label="Moderation"
            />
          </div>

          <div className="field-row">
            <div className="grow">
              <div className="label">Activity level</div>
              <div className="hint">How often new posts appear on their own.</div>
            </div>
            <div style={{ width: 170 }}>
              <Slider
                value={draft.activity_level}
                min={0}
                max={3}
                step={0.1}
                onChange={(value) => setDraft({ ...draft, activity_level: value })}
                format={(value) => `${value.toFixed(1)}×`}
              />
            </div>
          </div>

          <div className="field">
            <label>Icon &amp; colour</label>
            <div className="row">
              <input
                style={{ width: 70 }}
                value={draft.icon}
                onChange={(event) => setDraft({ ...draft, icon: event.target.value.slice(0, 4) })}
              />
              <input
                type="color"
                style={{ width: 60, padding: 2, height: 36 }}
                value={draft.color}
                onChange={(event) => setDraft({ ...draft, color: event.target.value })}
              />
            </div>
          </div>

          <div className="field">
            <label>Rules</label>
            <ChipInput values={draft.rules} onChange={(rules) => setDraft({ ...draft, rules })} />
          </div>

          <div className="field">
            <label>Recurring topics</label>
            <ChipInput values={draft.topics} onChange={(topics) => setDraft({ ...draft, topics })} />
          </div>

          <details>
            <summary className="card-title" style={{ cursor: 'pointer' }}>
              Board personality overrides
            </summary>
            <div style={{ marginTop: 10 }}>
              <OverrideSliders overrides={overrides} onChange={setOverrides} />
            </div>
          </details>

          <div className="divider" />
          <button className="btn btn-danger btn-sm" onClick={() => void removeBoard()}>
            Delete r/{board.name}
          </button>
        </>
      )}
    </Modal>
  );
}
