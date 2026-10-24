import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useApp } from '../lib/store';
import type { Award } from '../lib/types';
import { Modal, Switch } from './common';

export function AwardStrip({ awards }: { awards: Award[] }) {
  if (!awards.length) return null;
  return (
    <span className="awards-row">
      {awards.map((award) => (
        <span
          className="award-chip"
          key={award.id}
          title={`${award.name} — ${award.description}`}
          style={{ color: award.color }}
        >
          <span aria-hidden="true">{award.icon}</span>
          {(award.count ?? 1) > 1 ? <span>{award.count}</span> : null}
        </span>
      ))}
    </span>
  );
}

export function AwardPicker({
  kind,
  targetId,
  onClose,
  onGranted,
}: {
  kind: 'post' | 'comment';
  targetId: string;
  onClose: () => void;
  onGranted: (awards: Award[]) => void;
}) {
  const { user, notify, refresh } = useApp();
  const [catalogue, setCatalogue] = useState<Award[]>([]);
  const [coins, setCoins] = useState(user?.coins ?? 0);
  const [anonymous, setAnonymous] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void api.awards
      .catalogue()
      .then((data) => {
        setCatalogue(data.awards);
        setCoins(data.coins);
      })
      .catch(() => notify('Could not load awards.', 'error'));
  }, [notify]);

  const give = async (award: Award) => {
    setBusy(award.id);
    try {
      const result = await api.awards.give(kind, targetId, award.id, anonymous);
      setCoins(result.coins);
      onGranted(result.awards);
      notify(`You gave ${award.name} ${award.icon}`, 'success');
      await refresh();
      onClose();
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Award failed.', 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal
      title="Give an award"
      onClose={onClose}
      footer={
        <div className="row-between grow">
          <span className="small muted">
            Balance: <strong style={{ color: 'var(--warn)' }}>{coins.toLocaleString()}</strong> coins
          </span>
          <label className="row small muted" style={{ gap: 6 }}>
            <Switch checked={anonymous} onChange={setAnonymous} label="Give anonymously" />
            Anonymous
          </label>
        </div>
      }
    >
      <div className="award-grid">
        {catalogue.map((award) => (
          <button
            key={award.id}
            className="award-card"
            disabled={coins < award.cost || busy !== null}
            onClick={() => void give(award)}
            title={award.description}
          >
            <span className="icon" aria-hidden="true">
              {award.icon}
            </span>
            <span className="name" style={{ color: award.color }}>
              {award.name}
            </span>
            <span className="cost">{award.cost.toLocaleString()}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
