import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Avatar, ChipInput, Icon, Modal, Slider, Switch } from '../components/common';
import { api } from '../lib/api';
import { useApp } from '../lib/store';
import type { Board, Preferences } from '../lib/types';

const TABS = [
  { id: 'profile', label: 'Profile' },
  { id: 'feed', label: 'Feed & interests' },
  { id: 'ai', label: 'AI behaviour' },
  { id: 'boards', label: 'Boards' },
  { id: 'account', label: 'Account & data' },
];

const EMOJI = ['🦊', '🐙', '🦉', '🐸', '🦝', '🐝', '🦑', '🐢', '🦋', '🐧', '🦈', '🐺', '🪿', '🦔'];
const COLORS = ['#ff4500', '#0079d3', '#46d160', '#ffb000', '#ff66ac', '#7193ff', '#ea0027', '#9f7aea'];

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="card card-pad" style={{ marginBottom: 14 }}>
      <p className="card-title">{title}</p>
      {hint ? <p className="hint small" style={{ marginTop: -4 }}>{hint}</p> : null}
      {children}
    </div>
  );
}

export function SettingsPage() {
  const { user, notify, setUser, updatePreferences, signOut } = useApp();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'profile';

  const [profile, setProfile] = useState({
    display_name: user?.display_name ?? '',
    bio: user?.bio ?? '',
    avatar_color: user?.avatar_color ?? COLORS[0],
    avatar_emoji: user?.avatar_emoji ?? EMOJI[0],
    personal_prompt: user?.personal_prompt ?? '',
  });
  const [interests, setInterests] = useState<string[]>(user?.interests ?? []);
  const [boards, setBoards] = useState<Board[]>([]);
  const [wipeOpen, setWipeOpen] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!user) return;
    setProfile({
      display_name: user.display_name,
      bio: user.bio,
      avatar_color: user.avatar_color,
      avatar_emoji: user.avatar_emoji,
      personal_prompt: user.personal_prompt ?? '',
    });
    setInterests(user.interests ?? []);
  }, [user?.id]);

  useEffect(() => {
    void api.boards.list().then((data) => setBoards(data.boards)).catch(() => {});
  }, []);

  if (!user) {
    return (
      <div className="card card-pad">
        <p>Sign in or continue as a guest to change your settings.</p>
      </div>
    );
  }

  const preferences = user.preferences as Preferences;

  const setPreference = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    void updatePreferences({ [key]: value } as Partial<Preferences>).catch(() =>
      notify('Could not save that setting.', 'error'),
    );

  const saveProfile = async () => {
    setBusy(true);
    try {
      const { user: updated } = await api.me.profile(profile);
      setUser(updated);
      notify('Profile saved.', 'success');
    } catch {
      notify('Could not save your profile.', 'error');
    } finally {
      setBusy(false);
    }
  };

  const saveInterests = async () => {
    const { user: updated } = await api.me.interests(interests);
    setUser(updated);
    notify('Interests saved — your feed will start matching them.', 'success');
  };

  const exportData = async () => {
    const data = await api.me.exportData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `readit-${user.username}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <h1 style={{ fontSize: 22, marginTop: 0 }}>Settings</h1>
      <div className="tabs">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            className={`tab${tab === entry.id ? ' active' : ''}`}
            onClick={() => setParams({ tab: entry.id })}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === 'profile' ? (
        <>
          <Section title="How you appear">
            <div className="row" style={{ gap: 14, marginBottom: 14 }}>
              <Avatar color={profile.avatar_color} emoji={profile.avatar_emoji} size={64} />
              <div className="grow">
                <div className="field" style={{ marginBottom: 8 }}>
                  <label htmlFor="display-name">Display name</label>
                  <input
                    id="display-name"
                    value={profile.display_name}
                    onChange={(event) => setProfile({ ...profile, display_name: event.target.value })}
                  />
                </div>
                <div className="small muted">u/{user.username} · {user.is_guest ? 'guest account' : 'registered'}</div>
              </div>
            </div>

            <div className="field">
              <label>Avatar</label>
              <div className="row wrap" style={{ gap: 6 }}>
                {EMOJI.map((emoji) => (
                  <button
                    key={emoji}
                    className="btn-ghost"
                    style={{
                      fontSize: 20,
                      border: profile.avatar_emoji === emoji ? '2px solid var(--accent)' : '2px solid transparent',
                    }}
                    onClick={() => setProfile({ ...profile, avatar_emoji: emoji })}
                  >
                    {emoji}
                  </button>
                ))}
              </div>
              <div className="row wrap" style={{ gap: 6, marginTop: 6 }}>
                {COLORS.map((color) => (
                  <button
                    key={color}
                    onClick={() => setProfile({ ...profile, avatar_color: color })}
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: '50%',
                      background: color,
                      border: profile.avatar_color === color ? '3px solid var(--text)' : 'none',
                    }}
                    aria-label={`Colour ${color}`}
                  />
                ))}
              </div>
            </div>

            <div className="field">
              <label htmlFor="bio">Bio</label>
              <textarea
                id="bio"
                value={profile.bio}
                onChange={(event) => setProfile({ ...profile, bio: event.target.value })}
                placeholder="Tell the simulated masses about yourself"
              />
            </div>

            <button className="btn btn-primary" disabled={busy} onClick={() => void saveProfile()}>
              Save profile
            </button>
          </Section>

          <Section title="Appearance">
            <div className="field-row">
              <span className="label">Dark theme</span>
              <Switch
                checked={preferences.theme === 'dark'}
                onChange={(value) => setPreference('theme', value ? 'dark' : 'light')}
                label="Dark theme"
              />
            </div>
            <div className="field-row">
              <span className="label">Compact posts</span>
              <Switch
                checked={preferences.compact_mode}
                onChange={(value) => setPreference('compact_mode', value)}
                label="Compact posts"
              />
            </div>
            <div className="field-row">
              <div className="grow">
                <div className="label">Show the “human” badge</div>
                <div className="hint">Marks posts written by real accounts. Nothing marks the rest.</div>
              </div>
              <Switch
                checked={preferences.show_human_badges}
                onChange={(value) => setPreference('show_human_badges', value)}
                label="Human badges"
              />
            </div>
          </Section>

          <Section
            title="Reading font"
            hint="Applies to post and comment text everywhere on the site."
          >
            <div className="field-row">
              <div className="grow">
                <div className="label">Text size</div>
              </div>
              <div style={{ width: 190 }}>
                <Slider
                  value={preferences.content_font_size}
                  min={11}
                  max={20}
                  step={1}
                  onChange={(value) => setPreference('content_font_size', value)}
                  format={(value) => `${value}px`}
                />
              </div>
            </div>
            <div className="field">
              <label htmlFor="content-font-family">Custom font</label>
              <input
                id="content-font-family"
                defaultValue={preferences.content_font_family}
                onBlur={(event) => setPreference('content_font_family', event.target.value)}
                placeholder="Leave blank for the site default — e.g. 'Georgia', 'Atkinson Hyperlegible'"
              />
              <span className="hint">
                Must already be installed on your device or available as a system font; this
                doesn't load web fonts.
              </span>
            </div>
            <p
              className="small"
              style={{
                marginTop: 10,
                padding: 10,
                border: '1px solid var(--border)',
                borderRadius: 6,
                fontSize: `${preferences.content_font_size}px`,
                fontFamily: preferences.content_font_family
                  ? `"${preferences.content_font_family}", sans-serif`
                  : 'inherit',
              }}
            >
              Preview: the quick brown fox jumps over the lazy AI-generated dog.
            </p>
          </Section>
        </>
      ) : null}

      {tab === 'feed' ? (
        <>
          <Section
            title="Your interests"
            hint="Boards matching these get recommended, and their threads lean toward what you care about."
          >
            <ChipInput values={interests} onChange={setInterests} placeholder="e.g. woodworking, formula 1, cursed recipes" />
            <button className="btn btn-primary btn-sm" style={{ marginTop: 10 }} onClick={() => void saveInterests()}>
              Save interests
            </button>
          </Section>

          <Section title="Feed">
            <div className="field-row">
              <span className="label">Default sort</span>
              <select
                style={{ width: 160 }}
                value={preferences.feed_sort}
                onChange={(event) => setPreference('feed_sort', event.target.value)}
              >
                {['hot', 'new', 'top', 'rising', 'best'].map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
            <div className="field-row">
              <div className="grow">
                <div className="label">Live updates</div>
                <div className="hint">Let threads and feeds keep filling while you read them.</div>
              </div>
              <Switch
                checked={preferences.live_updates}
                onChange={(value) => setPreference('live_updates', value)}
                label="Live updates"
              />
            </div>
            <div className="field-row">
              <div className="grow">
                <div className="label">Show NSFW boards</div>
              </div>
              <Switch
                checked={preferences.show_nsfw}
                onChange={(value) => setPreference('show_nsfw', value)}
                label="Show NSFW"
              />
            </div>
            <div className="field-row">
              <div className="grow">
                <div className="label">Blur NSFW content</div>
              </div>
              <Switch
                checked={preferences.blur_nsfw}
                onChange={(value) => setPreference('blur_nsfw', value)}
                label="Blur NSFW"
              />
            </div>
            <div className="field-row">
              <div className="grow">
                <div className="label">Hide removed comments</div>
                <div className="hint">Off shows the “removed by moderator” stubs, like the real thing.</div>
              </div>
              <Switch
                checked={preferences.hide_removed}
                onChange={(value) => setPreference('hide_removed', value)}
                label="Hide removed"
              />
            </div>
          </Section>
        </>
      ) : null}

      {tab === 'ai' ? (
        <>
          <Section
            title="Your personal steer"
            hint="Layered on top of the site and board instructions, for everything generated for you."
          >
            <textarea
              value={profile.personal_prompt}
              onChange={(event) => setProfile({ ...profile, personal_prompt: event.target.value })}
              placeholder="e.g. 'keep the jokes dry and British', 'more technical depth', 'no politics'"
            />
            <button className="btn btn-primary btn-sm" style={{ marginTop: 10 }} onClick={() => void saveProfile()}>
              Save
            </button>
          </Section>

          <Section title="How threads behave for you">
            <div className="field-row">
              <div className="grow">
                <div className="label">Write comments when I open a thread</div>
                <div className="hint">Off means threads stay empty until you ask for discussion.</div>
              </div>
              <Switch
                checked={preferences.auto_generate_on_open}
                onChange={(value) => setPreference('auto_generate_on_open', value)}
                label="Auto generate"
              />
            </div>

            <div className="field-row">
              <div className="grow">
                <div className="label">Comment density</div>
                <div className="hint">How busy threads are when they load.</div>
              </div>
              <select
                style={{ width: 160 }}
                value={preferences.comment_density_override ?? ''}
                onChange={(event) =>
                  setPreference('comment_density_override', event.target.value || null)
                }
              >
                <option value="">use the board's setting</option>
                {['sparse', 'normal', 'busy', 'chaotic'].map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>

            <div className="field-row">
              <div className="grow">
                <div className="label">Intensity</div>
                <div className="hint">How harsh people are with each other in your threads.</div>
              </div>
              <div style={{ width: 190 }}>
                {preferences.content_intensity === null ? (
                  <button className="btn btn-ghost btn-sm" onClick={() => setPreference('content_intensity', 0.35)}>
                    using site default — override
                  </button>
                ) : (
                  <Slider
                    value={preferences.content_intensity}
                    onChange={(value) => setPreference('content_intensity', value)}
                  />
                )}
              </div>
            </div>

            <div className="field-row">
              <div className="grow">
                <div className="label">Humour</div>
              </div>
              <div style={{ width: 190 }}>
                {preferences.humor_override === null ? (
                  <button className="btn btn-ghost btn-sm" onClick={() => setPreference('humor_override', 0.55)}>
                    using site default — override
                  </button>
                ) : (
                  <Slider
                    value={preferences.humor_override}
                    onChange={(value) => setPreference('humor_override', value)}
                  />
                )}
              </div>
            </div>

            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="language-style">Voice preference</label>
              <input
                id="language-style"
                defaultValue={preferences.language_style}
                onBlur={(event) => setPreference('language_style', event.target.value)}
                placeholder="e.g. 'British spellings', 'shorter comments', 'no emoji'"
              />
            </div>
          </Section>
        </>
      ) : null}

      {tab === 'boards' ? (
        <>
          <Section title="Joined boards">
            {(user.subscriptions ?? []).length ? (
              <div className="stack" style={{ gap: 6 }}>
                {(user.subscriptions ?? []).map((name) => (
                  <div className="field-row" key={name}>
                    <span className="label">r/{name}</span>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={async () => {
                        const { user: updated } = await api.me.unsubscribe(name);
                        setUser(updated);
                      }}
                    >
                      Leave
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="small muted">You haven't joined any boards yet.</p>
            )}
          </Section>

          <Section title="Hidden boards" hint="These never appear in your feeds, search or sidebar.">
            {(user.banned_subreddits ?? []).length ? (
              <div className="stack" style={{ gap: 6 }}>
                {(user.banned_subreddits ?? []).map((name) => (
                  <div className="field-row" key={name}>
                    <span className="label">r/{name}</span>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={async () => {
                        const { user: updated } = await api.me.unblockBoard(name);
                        setUser(updated);
                      }}
                    >
                      Unhide
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="small muted">Nothing hidden.</p>
            )}
          </Section>

          <Section title="Hide a board">
            <select
              onChange={async (event) => {
                if (!event.target.value) return;
                const { user: updated } = await api.me.blockBoard(event.target.value);
                setUser(updated);
                notify(`r/${event.target.value} hidden.`, 'success');
                event.target.value = '';
              }}
            >
              <option value="">Choose a board to hide…</option>
              {boards
                .filter((board) => !(user.banned_subreddits ?? []).includes(board.name))
                .map((board) => (
                  <option key={board.id} value={board.name}>
                    r/{board.name}
                  </option>
                ))}
            </select>
          </Section>
        </>
      ) : null}

      {tab === 'account' ? (
        <>
          {user.is_guest ? (
            <Section title="Save this account" hint="Attach an email so your history survives this browser.">
              <button className="btn btn-primary" onClick={() => setPromoteOpen(true)}>
                Add an email and password
              </button>
            </Section>
          ) : (
            <Section title="Account">
              <dl className="kv">
                <dt>Email</dt>
                <dd>{user.email}</dd>
                <dt>Username</dt>
                <dd>u/{user.username}</dd>
                <dt>Post karma</dt>
                <dd>{user.karma.post}</dd>
                <dt>Comment karma</dt>
                <dd>{user.karma.comment}</dd>
                <dt>Coins</dt>
                <dd>{user.coins}</dd>
              </dl>
            </Section>
          )}

          <Section title="Your data" hint="Everything tied to this account: posts, comments, votes, boards.">
            <button className="btn btn-outline btn-sm" onClick={() => void exportData()}>
              Download my data (JSON)
            </button>
          </Section>

          <Section
            title="Delete everything I wrote"
            hint="Posts and comments stay in their threads as italic “removed” stubs, so replies underneath still make sense."
          >
            <button className="btn btn-danger btn-sm" onClick={() => setWipeOpen(true)}>
              {Icon.trash()} Wipe my content
            </button>
          </Section>

          <Section title="Session">
            <button className="btn btn-ghost btn-sm" onClick={() => void signOut()}>
              Log out
            </button>
          </Section>
        </>
      ) : null}

      {wipeOpen ? <WipeModal onClose={() => setWipeOpen(false)} /> : null}
      {promoteOpen ? <PromoteModal onClose={() => setPromoteOpen(false)} /> : null}
    </>
  );
}

function WipeModal({ onClose }: { onClose: () => void }) {
  const { notify, refresh, signOut } = useApp();
  const [confirm, setConfirm] = useState('');
  const [deleteAccount, setDeleteAccount] = useState(false);
  const [busy, setBusy] = useState(false);

  const wipe = async () => {
    setBusy(true);
    try {
      const result = await api.me.wipe(deleteAccount);
      notify(
        `${result.posts_wiped} posts and ${result.comments_wiped} comments wiped.`,
        'success',
      );
      if (result.account_deleted) await signOut();
      else await refresh();
      onClose();
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Wipe failed.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Wipe everything you wrote"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-danger"
            disabled={busy || confirm.trim().toUpperCase() !== 'WIPE'}
            onClick={() => void wipe()}
          >
            {busy ? 'Wiping…' : 'Wipe it all'}
          </button>
        </>
      }
    >
      <p className="small">
        Every post and comment you have written becomes an italic{' '}
        <em className="removed-stub">[removed]</em> stub. Your votes are dropped and your karma
        resets. Threads keep their shape, exactly like the real site.
      </p>
      <div className="field-row">
        <div className="grow">
          <div className="label">Also delete my account</div>
          <div className="hint">You will be signed out and cannot get the account back.</div>
        </div>
        <Switch checked={deleteAccount} onChange={setDeleteAccount} label="Delete account" />
      </div>
      <div className="field">
        <label htmlFor="wipe-confirm">Type WIPE to confirm</label>
        <input id="wipe-confirm" value={confirm} onChange={(event) => setConfirm(event.target.value)} />
      </div>
    </Modal>
  );
}

function PromoteModal({ onClose }: { onClose: () => void }) {
  const { user, upgradeGuest, notify } = useApp();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState(user?.username ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await upgradeGuest(email, password, username);
      notify('Account saved. Your karma and history came with you.', 'success');
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Save your guest account"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving…' : 'Save account'}
          </button>
        </>
      }
    >
      <p className="small muted">
        Everything you've done stays: karma, posts, comments, boards you created.
      </p>
      <div className="field">
        <label htmlFor="promote-username">Username</label>
        <input
          id="promote-username"
          value={username}
          onChange={(event) => setUsername(event.target.value.replace(/[^A-Za-z0-9_-]/g, ''))}
        />
      </div>
      <div className="field">
        <label htmlFor="promote-email">Email</label>
        <input id="promote-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="promote-password">Password</label>
        <input
          id="promote-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error ? <p className="small" style={{ color: 'var(--danger)' }}>{error}</p> : null}
    </Modal>
  );
}
