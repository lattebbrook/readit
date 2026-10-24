import { fireEvent, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeComment, makePost, preferences, renderWithRouter, user } from './fixtures';

/* The store and API are the only two seams these components talk to. */

const notify = vi.fn();
const storeState = { user, notify, refresh: vi.fn(), setUser: vi.fn() };

vi.mock('../lib/store', () => ({
  useApp: () => storeState,
}));

const vote = vi.fn();
const share = vi.fn();
const summonReplies = vi.fn();
const comment = vi.fn();
const savePost = vi.fn();
const unsavePost = vi.fn();

vi.mock('../lib/api', () => ({
  api: {
    vote: (...args: unknown[]) => vote(...args),
    share: (...args: unknown[]) => share(...args),
    report: vi.fn(),
    awards: { catalogue: vi.fn().mockResolvedValue({ awards: [], coins: 0 }), give: vi.fn() },
    posts: { comment: (...args: unknown[]) => comment(...args), remove: vi.fn() },
    comments: { summonReplies: (...args: unknown[]) => summonReplies(...args), edit: vi.fn(), remove: vi.fn() },
    me: {
      savePost: (...args: unknown[]) => savePost(...args),
      unsavePost: (...args: unknown[]) => unsavePost(...args),
    },
  },
}));

const navigateMock = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return { ...actual, useNavigate: () => navigateMock };
});

import { HumanBadge, ChipInput, Switch, Modal, Body } from '../components/common';
import { CommentTree } from '../components/CommentTree';
import { PostCard } from '../components/PostCard';
import { VoteBox } from '../components/VoteBox';

beforeEach(() => {
  vi.clearAllMocks();
  storeState.user = user;
});

/* ------------------------------------------------------------------ badge */

describe('HumanBadge', () => {
  it('renders for a real account', () => {
    renderWithRouter(
      <HumanBadge badge={{ kind: 'human', label: 'human', title: 'A real person' }} />,
    );
    expect(screen.getByText('human')).toBeInTheDocument();
  });

  it('renders nothing for a simulated account', () => {
    const { container } = renderWithRouter(<HumanBadge badge={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('can be switched off by preference', () => {
    const { container } = renderWithRouter(
      <HumanBadge badge={{ kind: 'human', label: 'human', title: 't' }} show={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

/* ---------------------------------------------------------------- votebox */

describe('VoteBox', () => {
  it('shows the current score', () => {
    renderWithRouter(<VoteBox kind="post" id="p1" score={1234} userVote={0} />);
    expect(screen.getByText('1.2k')).toBeInTheDocument();
  });

  it('marks the arrow the user already pressed', () => {
    renderWithRouter(<VoteBox kind="post" id="p1" score={10} userVote={1} />);
    expect(screen.getByLabelText('Upvote')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Downvote')).toHaveAttribute('aria-pressed', 'false');
  });

  it('sends the vote and adopts the server score', async () => {
    vote.mockResolvedValue({ score: 1235, ups: 1301, downs: 66, direction: 1 });
    renderWithRouter(<VoteBox kind="post" id="p1" score={1234} userVote={0} />);

    await userEvent.click(screen.getByLabelText('Upvote'));

    expect(vote).toHaveBeenCalledWith('post', 'p1', 1);
    await waitFor(() => expect(screen.getByText('1.2k')).toBeInTheDocument());
    expect(screen.getByLabelText('Upvote')).toHaveAttribute('aria-pressed', 'true');
  });

  it('rolls back when the request fails', async () => {
    vote.mockRejectedValue(new Error('nope'));
    renderWithRouter(<VoteBox kind="comment" id="c1" score={5} userVote={0} />);

    await userEvent.click(screen.getByLabelText('Downvote'));

    await waitFor(() => expect(screen.getByText('5')).toBeInTheDocument());
    expect(screen.getByLabelText('Downvote')).toHaveAttribute('aria-pressed', 'false');
    expect(notify).toHaveBeenCalledWith('That vote did not go through.', 'error');
  });

  it('asks anonymous readers to sign in instead of calling the API', async () => {
    storeState.user = null as never;
    renderWithRouter(<VoteBox kind="post" id="p1" score={3} userVote={0} />);

    await userEvent.click(screen.getByLabelText('Upvote'));

    expect(vote).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith('Sign in or continue as a guest to vote.', 'error');
  });
});

/* --------------------------------------------------------------- postcard */

describe('PostCard', () => {
  it('renders the byline, board and score', () => {
    renderWithRouter(<PostCard post={makePost()} />);
    expect(screen.getByText('A perfectly ordinary post')).toBeInTheDocument();
    expect(screen.getByText('u/GrumpyOtter')).toBeInTheDocument();
    expect(screen.getByText('r/testboard')).toBeInTheDocument();
    expect(screen.getByText('1.2k')).toBeInTheDocument();
  });

  it('shows the human capsule only for real authors', () => {
    const { rerender } = renderWithRouter(<PostCard post={makePost()} />);
    expect(screen.queryByText('human')).not.toBeInTheDocument();

    rerender(
      <PostCard
        post={makePost({ author_badge: { kind: 'human', label: 'human', title: 'A real person' } })}
      />,
    );
    expect(screen.getByText('human')).toBeInTheDocument();
  });

  it('renders the moderator removal stub', () => {
    renderWithRouter(
      <PostCard
        post={makePost({
          removed: true,
          removed_by: 'AutoModerator',
          removal_reason: 'Rule 1: Be civil',
          body: 'this text must not appear',
        })}
      />,
    );
    expect(screen.getByText('[removed]')).toBeInTheDocument();
    expect(screen.getByText(/Rule 1: Be civil/)).toBeInTheDocument();
    expect(screen.queryByText('this text must not appear')).not.toBeInTheDocument();
  });

  it('renders the author deletion stub', () => {
    renderWithRouter(<PostCard post={makePost({ deleted_by_author: true, body: 'gone' })} />);
    expect(screen.getByText('[deleted by the person who wrote it]')).toBeInTheDocument();
  });

  it('blurs NSFW posts until revealed', async () => {
    const { container } = renderWithRouter(<PostCard post={makePost({ nsfw: true })} />);
    expect(container.querySelector('.nsfw-blur')).toBeTruthy();

    await userEvent.click(screen.getByText('Show NSFW content'));
    expect(container.querySelector('.nsfw-blur')).toBeFalsy();
  });

  it('does not blur when the reader turned that off', () => {
    storeState.user = { ...user, preferences: { ...preferences, blur_nsfw: false } };
    const { container } = renderWithRouter(<PostCard post={makePost({ nsfw: true })} />);
    expect(container.querySelector('.nsfw-blur')).toBeFalsy();
  });

  it('marks locked threads', () => {
    renderWithRouter(<PostCard post={makePost({ locked: true })} />);
    expect(screen.getByText(/locked/)).toBeInTheDocument();
  });

  it('copies a permalink when sharing', async () => {
    share.mockResolvedValue({ url: '/r/testboard/comments/p1', shares: 1 });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    renderWithRouter(<PostCard post={makePost()} />);
    await userEvent.click(screen.getByText('Share'));

    await waitFor(() => expect(share).toHaveBeenCalledWith('post', 'p1'));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(expect.stringContaining('/r/testboard/comments/p1')),
    );
  });

  it('links the title on a card and renders a heading in detail view', () => {
    const { rerender } = renderWithRouter(<PostCard post={makePost()} />);
    expect(screen.getByRole('link', { name: 'A perfectly ordinary post' })).toBeInTheDocument();

    rerender(<PostCard post={makePost()} detail />);
    expect(screen.getByRole('heading', { name: 'A perfectly ordinary post' })).toBeInTheDocument();
  });

  it('opens the thread when clicking empty space on the card', async () => {
    navigateMock.mockClear();
    const { container } = renderWithRouter(<PostCard post={makePost()} />);

    const main = container.querySelector('.post-main')!;
    await userEvent.click(main);

    expect(navigateMock).toHaveBeenCalledWith('/r/testboard/comments/p1');
  });

  it('does not navigate when clicking a control inside the card', async () => {
    navigateMock.mockClear();
    renderWithRouter(<PostCard post={makePost()} />);

    await userEvent.click(screen.getByText('Share'));

    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('does not navigate at all in detail view', async () => {
    navigateMock.mockClear();
    const { container } = renderWithRouter(<PostCard post={makePost()} detail />);

    await userEvent.click(container.querySelector('.post-main')!);

    expect(navigateMock).not.toHaveBeenCalled();
  });

  it('toggles saved state and calls the API', async () => {
    savePost.mockResolvedValue({ user: {}, saved: true });
    renderWithRouter(<PostCard post={makePost({ saved: false })} />);

    await userEvent.click(screen.getByText('Save'));

    expect(savePost).toHaveBeenCalledWith('p1');
    await waitFor(() => expect(screen.getByText('Saved')).toBeInTheDocument());
  });

  it('unsaves an already-saved post', async () => {
    unsavePost.mockResolvedValue({ user: {}, saved: false });
    renderWithRouter(<PostCard post={makePost({ saved: true })} />);

    await userEvent.click(screen.getByText('Saved'));

    expect(unsavePost).toHaveBeenCalledWith('p1');
    await waitFor(() => expect(screen.getByText('Save')).toBeInTheDocument());
  });
});

/* ------------------------------------------------------------ commenttree */

describe('CommentTree', () => {
  const tree = [
    makeComment({
      id: 'c1',
      body: 'top level take',
      replies: [
        makeComment({ id: 'c2', parent_id: 'c1', body: 'nested disagreement', depth: 1 }),
      ],
    }),
  ];

  it('renders nested replies', () => {
    renderWithRouter(<CommentTree comments={tree} onReplied={vi.fn()} onChanged={vi.fn()} />);
    expect(screen.getByText('top level take')).toBeInTheDocument();
    expect(screen.getByText('nested disagreement')).toBeInTheDocument();
  });

  it('collapses a subtree and reports how much is hidden', async () => {
    renderWithRouter(<CommentTree comments={tree} onReplied={vi.fn()} onChanged={vi.fn()} />);

    await userEvent.click(screen.getAllByLabelText('Collapse')[0]);

    expect(screen.queryByText('top level take')).not.toBeInTheDocument();
    expect(screen.getByText(/1 hidden/)).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('Expand'));
    expect(screen.getByText('top level take')).toBeInTheDocument();
  });

  it('marks the thread author', () => {
    renderWithRouter(
      <CommentTree comments={[makeComment({ is_op: true })]} onReplied={vi.fn()} onChanged={vi.fn()} />,
    );
    expect(screen.getByText('OP')).toBeInTheDocument();
  });

  it('renders removal stubs instead of the original text', () => {
    renderWithRouter(
      <CommentTree
        comments={[
          makeComment({
            removed: true,
            removed_by: 'AutoModerator',
            removal_reason: 'Rule 3: No personal attacks',
            body: '[removed]',
          }),
        ]}
        onReplied={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText('[removed]')).toBeInTheDocument();
    expect(screen.getByText(/Rule 3: No personal attacks/)).toBeInTheDocument();
  });

  it('posts a reply and hands it back to the parent', async () => {
    const created = makeComment({ id: 'new', parent_id: 'c1', body: 'my reply' });
    comment.mockResolvedValue({ comment: created });
    const onReplied = vi.fn();

    renderWithRouter(<CommentTree comments={tree} onReplied={onReplied} onChanged={vi.fn()} />);

    await userEvent.click(screen.getAllByText('Reply')[0]);
    const box = screen.getByPlaceholderText('Reply to u/TiredBarnacle79…');
    fireEvent.change(box, { target: { value: 'my reply' } });
    // Two controls read "Reply": the toggle and the submit button in the composer.
    const submit = box.closest('.composer')!.querySelector('.btn-primary') as HTMLButtonElement;
    await userEvent.click(submit);

    await waitFor(() => expect(comment).toHaveBeenCalledWith('p1', 'my reply', 'c1'));
    expect(onReplied).toHaveBeenCalledWith(created);
  });

  it('hides reply controls on a locked thread', () => {
    renderWithRouter(
      <CommentTree comments={tree} onReplied={vi.fn()} onChanged={vi.fn()} locked />,
    );
    expect(screen.queryByText('Reply')).not.toBeInTheDocument();
    expect(screen.queryByText('Poke')).not.toBeInTheDocument();
  });

  it('pokes a comment to summon more replies', async () => {
    summonReplies.mockResolvedValue({ created: 3, comments: [] });
    renderWithRouter(<CommentTree comments={tree} onReplied={vi.fn()} onChanged={vi.fn()} />);

    await userEvent.click(screen.getAllByText('Poke')[0]);

    await waitFor(() => expect(summonReplies).toHaveBeenCalledWith('c1', 3));
  });

  it('offers edit and delete only on your own comments', async () => {
    const { rerender, container } = renderWithRouter(
      <CommentTree comments={[makeComment()]} onReplied={vi.fn()} onChanged={vi.fn()} />,
    );
    expect(container.querySelector('.dropdown')).toBeNull();

    rerender(
      <CommentTree comments={[makeComment({ is_own: true })]} onReplied={vi.fn()} onChanged={vi.fn()} />,
    );
    await userEvent.click(container.querySelector('.dropdown button')!);
    expect(screen.getByText('Edit')).toBeInTheDocument();
    expect(screen.getByText('Delete')).toBeInTheDocument();
  });

  it('shows the "continue this thread" affordance past the depth cap', () => {
    renderWithRouter(
      <CommentTree
        comments={[makeComment({ hidden_replies: 7 })]}
        onReplied={vi.fn()}
        onChanged={vi.fn()}
      />,
    );
    expect(screen.getByText(/continue this thread/)).toBeInTheDocument();
  });
});

/* --------------------------------------------------------------- controls */

describe('shared controls', () => {
  it('Switch toggles and reports its state', async () => {
    const onChange = vi.fn();
    renderWithRouter(<Switch checked={false} onChange={onChange} label="Live updates" />);

    const control = screen.getByRole('switch', { name: 'Live updates' });
    expect(control).toHaveAttribute('aria-checked', 'false');
    await userEvent.click(control);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('ChipInput adds, deduplicates and removes values', async () => {
    let values: string[] = [];
    const onChange = vi.fn((next: string[]) => {
      values = next;
    });
    const { rerender } = renderWithRouter(<ChipInput values={values} onChange={onChange} />);

    const box = screen.getByRole('textbox');
    await userEvent.type(box, 'woodworking{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(['woodworking']);

    rerender(<ChipInput values={['woodworking']} onChange={onChange} />);
    await userEvent.clear(screen.getByRole('textbox'));
    await userEvent.type(screen.getByRole('textbox'), 'woodworking{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(['woodworking']);

    await userEvent.click(screen.getByLabelText('Remove woodworking'));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('Modal closes on the escape key and the backdrop', async () => {
    const onClose = vi.fn();
    const { container } = renderWithRouter(
      <Modal title="Board settings" onClose={onClose}>
        body
      </Modal>,
    );

    expect(screen.getByRole('dialog', { name: 'Board settings' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(container.querySelector('.modal-backdrop')!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it('Body renders escaped markdown-ish content', () => {
    const { container } = renderWithRouter(<Body text={'**bold** <img src=x onerror=1>'} />);
    expect(container.querySelector('strong')?.textContent).toBe('bold');
    expect(container.querySelector('img')).toBeNull();
  });
});
