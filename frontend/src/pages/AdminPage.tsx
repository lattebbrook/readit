import { useCallback, useEffect, useState } from 'react';
import { Modal, Slider, Spinner, Switch } from '../components/common';
import { api } from '../lib/api';
import { useApp } from '../lib/store';
import type { LLMConfig, LLMConnection, WorldConfig } from '../lib/types';

const TABS = [
  { id: 'world', label: 'World prompt' },
  { id: 'ai', label: 'AI connections' },
  { id: 'sim', label: 'Simulation' },
  { id: 'oversight', label: 'Oversight' },
];

// Provider type strings are machine-friendly; a few need a nicer label than
// naive title-casing would produce.
const PROVIDER_LABELS: Record<string, string> = {
  lmstudio: 'LM Studio',
  openai_compatible: 'OpenAI-compatible',
};

const WORLD_KNOBS: { key: keyof WorldConfig; label: string; hint: string }[] = [
  { key: 'humor', label: 'Humour', hint: 'How much of the site is jokes' },
  { key: 'toxicity', label: 'Meanness', hint: 'How harsh people are with each other' },
  { key: 'argument_rate', label: 'Argument rate', hint: 'How often threads become fights' },
  { key: 'wholesomeness', label: 'Warmth', hint: 'Kindness and sincerity' },
  { key: 'shitpost_rate', label: 'Shitposting', hint: 'Low-effort nonsense' },
  { key: 'expertise', label: 'Expertise', hint: 'How many people actually know things' },
  { key: 'moderation_strictness', label: 'Mod strictness', hint: 'How eagerly mods step in' },
  { key: 'removal_rate', label: 'Removal rate', hint: 'How much content gets taken down' },
  { key: 'award_rate', label: 'Award rate', hint: 'How freely people give awards' },
  { key: 'user_vote_bonus', label: 'Human vote bonus', hint: 'How much friendlier votes are to real users' },
  { key: 'vote_volatility', label: 'Vote volatility', hint: 'How swingy scores are' },
];

const PRESETS: { name: string; description: string; changes: Partial<WorldConfig> }[] = [
  {
    name: 'Classic',
    description: 'A big general forum. Curious, funny, occasionally hostile.',
    changes: { serious_mode: false, humor: 0.55, toxicity: 0.35, argument_rate: 0.3, wholesomeness: 0.4, expertise: 0.45 },
  },
  {
    name: 'Comedy club',
    description: 'Everything is a bit. Nobody answers the question.',
    changes: { serious_mode: false, humor: 0.95, shitpost_rate: 0.8, expertise: 0.15, toxicity: 0.3, argument_rate: 0.2 },
  },
  {
    name: 'Bloodsport',
    description: 'Everyone is furious and nobody backs down.',
    changes: { serious_mode: false, toxicity: 0.9, argument_rate: 0.95, wholesomeness: 0.05, moderation_strictness: 0.2, removal_rate: 0.05 },
  },
  {
    name: 'Serious Mode',
    description: 'Board-wide focus: substantive posts and replies, no trolling, derails, or joke-only noise—even on NSFW boards.',
    changes: {
      serious_mode: true,
      expertise: 0.9,
      toxicity: 0.15,
      humor: 0.1,
      argument_rate: 0.3,
      shitpost_rate: 0,
      moderation_strictness: 0.8,
      removal_rate: 0.15,
    },
  },
  {
    name: 'Group hug',
    description: 'Relentlessly supportive. Strangers helping strangers.',
    changes: { serious_mode: false, wholesomeness: 0.95, toxicity: 0.05, argument_rate: 0.08, award_rate: 0.35 },
  },
];

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="card card-pad" style={{ marginBottom: 14 }}>
      <p className="card-title">{title}</p>
      {hint ? <p className="hint small" style={{ marginTop: -4 }}>{hint}</p> : null}
      {children}
    </div>
  );
}

function WorldTab() {
  const { notify, refresh } = useApp();
  const [world, setWorld] = useState<WorldConfig | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.admin.world().then((data) => setWorld(data.world)).catch(() => notify('Could not load world config.', 'error'));
  }, [notify]);

  if (!world) return <Spinner label="Loading the world…" />;

  const save = async (changes: Partial<WorldConfig>) => {
    setBusy(true);
    try {
      const { world: updated } = await api.admin.updateWorld(changes as Record<string, unknown>);
      setWorld(updated);
      await refresh();
      notify('World updated. New content will follow it immediately.', 'success');
    } catch {
      notify('Could not save that.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Section
        title="Global prompt"
        hint="The single instruction behind every post and comment on the site. Change it and the whole place changes character."
      >
        <textarea
          style={{ minHeight: 190 }}
          value={world.global_prompt}
          onChange={(event) => setWorld({ ...world, global_prompt: event.target.value })}
        />
        <div className="row" style={{ gap: 8, marginTop: 10 }}>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save({ global_prompt: world.global_prompt })}>
            Save global prompt
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={async () => {
              const { world: reset } = await api.admin.resetWorld();
              setWorld(reset);
              notify('World reset to defaults.', 'success');
            }}
          >
            Reset to default
          </button>
        </div>
      </Section>

      <Section title="Writing style" hint="How people type. Applies on top of the global prompt.">
        <textarea
          value={world.style_prompt}
          onChange={(event) => setWorld({ ...world, style_prompt: event.target.value })}
        />
        <button
          className="btn btn-primary btn-sm"
          style={{ marginTop: 10 }}
          disabled={busy}
          onClick={() => void save({ style_prompt: world.style_prompt })}
        >
          Save style
        </button>
      </Section>

      <Section title="Presets" hint="One click to swing the entire site's personality.">
        <div className="row wrap" style={{ gap: 8 }}>
          {PRESETS.map((preset) => (
            <button
              key={preset.name}
              className={`btn btn-sm ${preset.name === 'Serious Mode' && world.serious_mode ? 'btn-primary' : 'btn-outline'}`}
              title={preset.description}
              onClick={() => void save(preset.changes)}
            >
              {preset.name}
            </button>
          ))}
        </div>
        {world.serious_mode ? (
          <p className="hint small" style={{ marginTop: 10 }}>
            Serious Mode is active across every board. It overrides board and reader humour settings,
            while still allowing relevant adult discussion on NSFW boards.
          </p>
        ) : null}
      </Section>

      <Section title="Behaviour" hint="These feed straight into every generation prompt.">
        {WORLD_KNOBS.map((knob) => (
          <div className="field-row" key={String(knob.key)}>
            <div className="grow">
              <div className="label">{knob.label}</div>
              <div className="hint tiny">{knob.hint}</div>
            </div>
            <div style={{ width: 190 }}>
              <Slider
                value={Number(world[knob.key] ?? 0.5)}
                onChange={(value) => {
                  setWorld({ ...world, [knob.key]: value });
                  void save({ [knob.key]: value } as Partial<WorldConfig>);
                }}
              />
            </div>
          </div>
        ))}

        <div className="field-row">
          <div className="grow">
            <div className="label">Comment density</div>
            <div className="hint tiny">How busy threads get by default</div>
          </div>
          <select
            style={{ width: 190 }}
            value={world.comment_density}
            onChange={(event) => void save({ comment_density: event.target.value })}
          >
            {['sparse', 'normal', 'busy', 'chaotic'].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="field-row">
          <div className="grow">
            <div className="label">Max comments per thread</div>
          </div>
          <input
            type="number"
            style={{ width: 190 }}
            value={world.max_comments_per_thread}
            onChange={(event) => setWorld({ ...world, max_comments_per_thread: Number(event.target.value) })}
            onBlur={(event) => void save({ max_comments_per_thread: Number(event.target.value) })}
          />
        </div>

        <div className="field-row">
          <div className="grow">
            <div className="label">Moderation</div>
            <div className="hint tiny">Off means nothing is ever removed anywhere.</div>
          </div>
          <Switch
            checked={world.moderation_enabled}
            onChange={(value) => void save({ moderation_enabled: value })}
            label="Moderation"
          />
        </div>

        <div className="field-row">
          <div className="grow">
            <div className="label">Allow NSFW boards</div>
          </div>
          <Switch checked={world.allow_nsfw} onChange={(value) => void save({ allow_nsfw: value })} label="Allow NSFW" />
        </div>
      </Section>
    </>
  );
}

function ConnectionModal({
  onClose,
  onSaved,
  providerTypes,
  suggested,
  editing,
}: {
  onClose: () => void;
  onSaved: (config: LLMConfig) => void;
  providerTypes: string[];
  suggested: Record<string, string[]>;
  /** Present -> editing this existing connection; absent -> creating a new one. */
  editing?: LLMConnection | null;
}) {
  const { notify } = useApp();
  const [providerType, setProviderType] = useState(editing?.provider_type ?? 'openrouter');
  const [name, setName] = useState(editing?.name ?? 'OpenRouter');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState(editing?.base_url ?? '');
  const [models, setModels] = useState<string>(
    (editing?.models ?? suggested.openrouter ?? []).join('\n'),
  );
  const [busy, setBusy] = useState(false);

  const displayName = (type: string) =>
    PROVIDER_LABELS[type] ?? type.replace('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase());

  const pick = (type: string) => {
    setProviderType(type);
    setName(displayName(type));
    setModels((suggested[type] ?? []).join('\n'));
  };

  const save = async () => {
    setBusy(true);
    try {
      const payload = {
        name,
        provider_type: providerType,
        api_key: apiKey,
        base_url: baseUrl,
        models: models.split('\n').map((line) => line.trim()).filter(Boolean),
      };
      const { config } = editing
        ? await api.admin.updateConnection(editing.id, payload)
        : await api.admin.addConnection(payload);
      onSaved(config);
      notify(editing ? `${name} updated.` : `${name} connected.`, 'success');
      onClose();
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Could not save that connection.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={editing ? `Edit ${editing.name}` : 'Add an AI connection'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving…' : editing ? 'Save changes' : 'Add connection'}
          </button>
        </>
      }
    >
      <div className="field">
        <label>Provider</label>
        <div className="row wrap" style={{ gap: 6 }}>
          {providerTypes.map((type) => (
            <button
              key={type}
              className={`btn btn-sm ${providerType === type ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => pick(type)}
            >
              {displayName(type)}
            </button>
          ))}
        </div>
        {providerType === 'openrouter' ? (
          <span className="hint">
            One endpoint, every vendor's models. List several below and the site will spread its
            voices across them.
          </span>
        ) : null}
        {providerType === 'mock' ? (
          <span className="hint">The built-in offline generator. No key, no network, no cost.</span>
        ) : null}
        {providerType === 'lmstudio' ? (
          <span className="hint">
            Point this at a running LM Studio server. Defaults to{' '}
            <code>http://localhost:1234/v1</code> — no API key needed. Add the connection, then
            use "Fetch models" to pull in whatever you currently have loaded.
          </span>
        ) : null}
      </div>

      <div className="field">
        <label htmlFor="conn-name">Label</label>
        <input id="conn-name" value={name} onChange={(event) => setName(event.target.value)} />
      </div>

      {providerType !== 'mock' ? (
        <div className="field">
          <label htmlFor="conn-key">
            API key{providerType === 'lmstudio' ? ' (optional)' : ''}
          </label>
          <input
            id="conn-key"
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={
              editing
                ? `Leave blank to keep ${editing.api_key_preview || 'the current key'}`
                : providerType === 'lmstudio'
                  ? 'Not required unless your server sits behind an auth proxy'
                  : 'sk-…'
            }
            autoComplete="off"
          />
          <span className="hint">Stored server-side and never sent back to this page.</span>
        </div>
      ) : null}

      <div className="field">
        <label htmlFor="conn-url">Base URL (optional)</label>
        <input
          id="conn-url"
          value={baseUrl}
          onChange={(event) => setBaseUrl(event.target.value)}
          placeholder={
            providerType === 'lmstudio'
              ? 'Leave blank for http://localhost:1234/v1'
              : 'Leave blank for the provider default'
          }
        />
      </div>

      <div className="field">
        <label htmlFor="conn-models">Models, one per line</label>
        <textarea id="conn-models" value={models} onChange={(event) => setModels(event.target.value)} />
      </div>
    </Modal>
  );
}

function AITab() {
  const { notify, refresh } = useApp();
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [providerTypes, setProviderTypes] = useState<string[]>([]);
  const [suggested, setSuggested] = useState<Record<string, string[]>>({});
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<LLMConnection | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const data = await api.admin.llm();
      setConfig(data.config);
      setProviderTypes(data.provider_types);
      setSuggested(data.suggested_models);
    } catch {
      notify('Could not load AI settings.', 'error');
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!config) return <Spinner label="Loading connections…" />;

  const test = async (id: string) => {
    setTesting(id);
    try {
      const result = await api.admin.testConnection(id);
      setResults({
        ...results,
        [id]: result.ok ? `ok · ${result.latency_ms}ms · "${result.sample.slice(0, 40)}"` : `failed · ${result.error}`,
      });
    } finally {
      setTesting(null);
    }
  };

  return (
    <>
      <Section
        title="Connections"
        hint="Add one or more providers. With several enabled, different boards and comments come from different models."
      >
        {config.connections.length ? (
          <div className="stack" style={{ gap: 10 }}>
            {config.connections.map((connection) => (
              <div className="card card-pad" key={connection.id} style={{ background: 'var(--surface-2)' }}>
                <div className="row-between">
                  <div>
                    <strong>{connection.name}</strong>{' '}
                    <span className="pill">{connection.provider_type}</span>{' '}
                    {connection.enabled ? (
                      <span className="pill ok">enabled</span>
                    ) : (
                      <span className="pill bad">disabled</span>
                    )}
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    <Switch
                      checked={connection.enabled}
                      onChange={async (value) => {
                        const { config: updated } = await api.admin.updateConnection(connection.id, {
                          enabled: value,
                        });
                        setConfig(updated);
                        await refresh();
                      }}
                      label="Enabled"
                    />
                    <button className="btn btn-ghost btn-sm" disabled={testing === connection.id} onClick={() => void test(connection.id)}>
                      {testing === connection.id ? 'testing…' : 'Test'}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditing(connection)}>
                      Edit
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={async () => {
                        const { config: updated, models } = await api.admin.discoverModels(connection.id);
                        setConfig(updated);
                        notify(`${models.length} models found.`, models.length ? 'success' : 'error');
                      }}
                    >
                      Fetch models
                    </button>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={async () => {
                        if (!window.confirm(`Remove ${connection.name}?`)) return;
                        const { config: updated } = await api.admin.deleteConnection(connection.id);
                        setConfig(updated);
                        await refresh();
                      }}
                    >
                      Remove
                    </button>
                  </div>
                </div>
                <div className="tiny muted" style={{ marginTop: 6 }}>
                  key {connection.api_key_preview || '—'} · {connection.models.length} models
                  {connection.base_url ? ` · ${connection.base_url}` : ''}
                </div>
                {results[connection.id] ? (
                  <div
                    className="tiny"
                    style={{
                      marginTop: 6,
                      color: results[connection.id].startsWith('ok') ? 'var(--ok)' : 'var(--danger)',
                    }}
                  >
                    {results[connection.id]}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        ) : (
          <p className="small muted">
            No providers connected. The site is running on its built-in offline generator, which
            works but writes far less convincingly.
          </p>
        )}

        <button className="btn btn-primary btn-sm" style={{ marginTop: 12 }} onClick={() => setAdding(true)}>
          Add a connection
        </button>
      </Section>

      <Section title="Model routing" hint="Point each kind of generation at a specific connection and model.">
        {Object.entries(config.roles).map(([role, settings]) => {
          const connection = config.connections.find((entry) => entry.id === settings.connection_id);
          return (
            <div className="field-row" key={role}>
              <div className="grow">
                <div className="label">{role}</div>
                <div className="hint tiny">
                  {role === 'post'
                    ? 'Writes new threads'
                    : role === 'comment'
                      ? 'Writes the discussion — the hot path'
                      : role === 'moderation'
                        ? 'Decides what gets removed'
                        : role === 'persona'
                          ? 'Invents the regulars'
                          : role === 'vision'
                            ? 'Describes images — needs a vision model. Runs once per picture, never per comment, so a slower model is fine here.'
                            : 'Board metadata and odd jobs'}
                </div>
              </div>
              <select
                style={{ width: 160 }}
                value={settings.connection_id ?? ''}
                onChange={async (event) => {
                  const { config: updated } = await api.admin.setRole(role, {
                    connection_id: event.target.value || null,
                    model: '',
                  });
                  setConfig(updated);
                }}
              >
                <option value="">auto</option>
                {config.connections.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name}
                  </option>
                ))}
              </select>
              <select
                style={{ width: 200 }}
                value={settings.model}
                onChange={async (event) => {
                  const { config: updated } = await api.admin.setRole(role, {
                    connection_id: settings.connection_id,
                    model: event.target.value,
                  });
                  setConfig(updated);
                }}
              >
                <option value="">any model</option>
                {(connection?.models ?? []).map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
      </Section>

      <Section title="Routing behaviour">
        <div className="field-row">
          <div className="grow">
            <div className="label">Mix models</div>
            <div className="hint tiny">Spread generation across every enabled connection so voices differ.</div>
          </div>
          <Switch
            checked={config.multi_model_mixing}
            onChange={async (value) => {
              const { config: updated } = await api.admin.setFlags({ multi_model_mixing: value });
              setConfig(updated);
            }}
            label="Mix models"
          />
        </div>
        <div className="field-row">
          <div className="grow">
            <div className="label">Fall back to the offline generator</div>
            <div className="hint tiny">Keeps the site alive when every provider fails.</div>
          </div>
          <Switch
            checked={config.fallback_to_mock}
            onChange={async (value) => {
              const { config: updated } = await api.admin.setFlags({ fallback_to_mock: value });
              setConfig(updated);
            }}
            label="Fallback"
          />
        </div>
      </Section>

      {adding ? (
        <ConnectionModal
          onClose={() => setAdding(false)}
          onSaved={(updated) => {
            setConfig(updated);
            void refresh();
          }}
          providerTypes={providerTypes}
          suggested={suggested}
        />
      ) : null}

      {editing ? (
        <ConnectionModal
          editing={editing}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setConfig(updated);
            void refresh();
          }}
          providerTypes={providerTypes}
          suggested={suggested}
        />
      ) : null}
    </>
  );
}

function SimulationTab() {
  const { notify } = useApp();
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [world, setWorld] = useState<WorldConfig | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus(await api.admin.simulation());
    setWorld((await api.admin.world()).world);
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 8000);
    return () => clearInterval(timer);
  }, [load]);

  if (!world || !status) return <Spinner label="Reading the engine…" />;

  const engine = (status.status ?? {}) as Record<string, unknown>;

  return (
    <>
      <Section title="Engine" hint="The background world: late replies, new posts, score drift, moderation.">
        <dl className="kv">
          <dt>Running</dt>
          <dd>{engine.running ? 'yes' : 'no'}</dd>
          <dt>Ticks</dt>
          <dd>{String(engine.ticks ?? 0)}</dd>
          <dt>Generations</dt>
          <dd>{String(engine.generations ?? 0)}</dd>
          <dt>Watched threads</dt>
          <dd>{String(engine.watched_threads ?? 0)}</dd>
          <dt>Last error</dt>
          <dd>{String(engine.last_error ?? '—')}</dd>
        </dl>
        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <button
            className="btn btn-primary btn-sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              const result = await api.admin.tick();
              notify(`Tick done: ${JSON.stringify(result.tick)}`, 'success');
              await load();
              setBusy(false);
            }}
          >
            Run one tick now
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={async () => {
              await (world.simulation_enabled ? api.admin.stopSimulation() : api.admin.startSimulation());
              await load();
            }}
          >
            {world.simulation_enabled ? 'Pause the world' : 'Resume the world'}
          </button>
        </div>
      </Section>

      <Section title="Pacing">
        <div className="field-row">
          <div className="grow">
            <div className="label">Background activity</div>
            <div className="hint tiny">Late replies and new posts arriving on their own.</div>
          </div>
          <Switch
            checked={world.background_activity}
            onChange={async (value) => {
              const { world: updated } = await api.admin.updateWorld({ background_activity: value });
              setWorld(updated);
            }}
            label="Background activity"
          />
        </div>
        <div className="field-row">
          <div className="grow">
            <div className="label">Seconds between ticks</div>
          </div>
          <input
            type="number"
            style={{ width: 160 }}
            value={world.tick_seconds}
            onChange={(event) => setWorld({ ...world, tick_seconds: Number(event.target.value) })}
            onBlur={async (event) => {
              const { world: updated } = await api.admin.updateWorld({
                tick_seconds: Number(event.target.value),
              });
              setWorld(updated);
            }}
          />
        </div>
        <div className="field-row">
          <div className="grow">
            <div className="label">Target posts per board</div>
          </div>
          <input
            type="number"
            style={{ width: 160 }}
            value={world.posts_per_board_target}
            onChange={(event) => setWorld({ ...world, posts_per_board_target: Number(event.target.value) })}
            onBlur={async (event) => {
              const { world: updated } = await api.admin.updateWorld({
                posts_per_board_target: Number(event.target.value),
              });
              setWorld(updated);
            }}
          />
        </div>
      </Section>

      <Section title="Content" hint="Bulk actions on the generated world. Accounts are never touched.">
        <div className="row wrap" style={{ gap: 8 }}>
          <button
            className="btn btn-outline btn-sm"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              await api.admin.seed(6, 5);
              notify('Boards seeded.', 'success');
              setBusy(false);
            }}
          >
            Fill empty boards
          </button>
          <button
            className="btn btn-outline btn-sm"
            onClick={async () => {
              await api.admin.generatePersonas(12);
              notify('New regulars created.', 'success');
            }}
          >
            Invent 12 new users
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={async () => {
              const { path } = await api.admin.snapshot();
              notify(`Snapshot saved to ${path}`, 'success');
            }}
          >
            Save snapshot
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={async () => {
              if (!window.confirm('Delete every post and comment on the site? Accounts survive.')) return;
              await api.admin.resetWorldContent(true);
              notify('World reset.', 'success');
            }}
          >
            Wipe all content
          </button>
        </div>
      </Section>
    </>
  );
}

function OversightTab() {
  const [stats, setStats] = useState<Record<string, unknown> | null>(null);
  const [modLog, setModLog] = useState<Record<string, unknown>[]>([]);
  const [calls, setCalls] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void api.admin.stats().then(setStats);
    void api.admin.modLog().then((data) => setModLog(data.entries.slice(0, 25)));
    void api.admin.calls().then((data) => setCalls(data.calls.slice(0, 25)));
  }, []);

  if (!stats) return <Spinner label="Counting things…" />;

  const collections = (stats.collections ?? {}) as Record<string, number>;
  const llm = (stats.llm ?? {}) as Record<string, unknown>;

  return (
    <>
      <Section title="Database">
        <dl className="kv">
          {Object.entries(collections).map(([name, count]) => (
            <div key={name} style={{ display: 'contents' }}>
              <dt>{name}</dt>
              <dd>{count}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title="Model calls">
        <dl className="kv">
          <dt>Total</dt>
          <dd>{String(llm.total ?? 0)}</dd>
          <dt>Succeeded</dt>
          <dd>{String(llm.ok ?? 0)}</dd>
          <dt>Failed</dt>
          <dd>{String(llm.failed ?? 0)}</dd>
          <dt>Average latency</dt>
          <dd>{String(llm.avg_latency_ms ?? 0)}ms</dd>
        </dl>
        {calls.length ? (
          <table className="table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>role</th>
                <th>model</th>
                <th>ms</th>
                <th>ok</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((call, index) => (
                <tr key={index}>
                  <td>{String(call.role)}</td>
                  <td>{String(call.model)}</td>
                  <td>{String(call.latency_ms)}</td>
                  <td>{call.ok ? '✓' : <span style={{ color: 'var(--danger)' }}>✕</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </Section>

      <Section title="Moderator actions">
        {modLog.length ? (
          <table className="table">
            <thead>
              <tr>
                <th>board</th>
                <th>action</th>
                <th>moderator</th>
                <th>reason</th>
              </tr>
            </thead>
            <tbody>
              {modLog.map((entry, index) => (
                <tr key={index}>
                  <td>r/{String(entry.subreddit)}</td>
                  <td>{String(entry.action).replace('_', ' ')}</td>
                  <td>{String(entry.moderator)}</td>
                  <td>{String(entry.reason)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="small muted">Nothing has been removed yet.</p>
        )}
      </Section>
    </>
  );
}

export function AdminPage() {
  const { user } = useApp();
  const [tab, setTab] = useState('world');

  if (!user?.is_admin) {
    return (
      <div className="card card-pad">
        <h1 style={{ fontSize: 20, marginTop: 0 }}>Admin console</h1>
        <p className="muted">
          You need an admin account. Sign in with the bootstrap admin email configured on the
          server (<code>READIT_ADMIN_EMAIL</code>, default <code>admin@readit.local</code>).
        </p>
      </div>
    );
  }

  return (
    <>
      <h1 style={{ fontSize: 22, marginTop: 0 }}>Admin console</h1>
      <div className="admin-nav">
        {TABS.map((entry) => (
          <button
            key={entry.id}
            className={`tab${tab === entry.id ? ' active' : ''}`}
            onClick={() => setTab(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>
      {tab === 'world' ? <WorldTab /> : null}
      {tab === 'ai' ? <AITab /> : null}
      {tab === 'sim' ? <SimulationTab /> : null}
      {tab === 'oversight' ? <OversightTab /> : null}
    </>
  );
}
