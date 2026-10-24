import { MemoryRouter } from 'react-router-dom';
import type { ReactElement } from 'react';
import { render } from '@testing-library/react';
import type { Board, Comment, Post, Preferences, User } from '../lib/types';

export const preferences: Preferences = {
  theme: 'dark',
  compact_mode: false,
  feed_sort: 'hot',
  show_nsfw: false,
  blur_nsfw: true,
  live_updates: true,
  auto_generate_on_open: true,
  comment_density_override: null,
  content_intensity: null,
  humor_override: null,
  hide_removed: false,
  show_human_badges: true,
  open_links_in_new_tab: true,
  notification_replies: true,
  language_style: '',
  content_font_size: 13,
  content_font_family: '',
};

export const user: User = {
  id: 'u1',
  username: 'samwise',
  display_name: 'samwise',
  bio: '',
  avatar_color: '#ff4500',
  avatar_emoji: '🦊',
  banner_color: '#1a1a1b',
  karma: { post: 10, comment: 20 },
  is_guest: false,
  is_admin: false,
  kind: 'human',
  created_at: 1_700_000_000,
  awards_received: {},
  coins: 500,
  subscriptions: [],
  interests: [],
  banned_subreddits: [],
  preferences,
  personal_prompt: '',
};

export function makePost(overrides: Partial<Post> = {}): Post {
  return {
    id: 'p1',
    subreddit: 'testboard',
    title: 'A perfectly ordinary post',
    body: 'with a body',
    kind: 'text',
    link_url: '',
    flair: '',
    author: 'GrumpyOtter',
    author_id: null,
    author_badge: null,
    score: 1234,
    ups: 1300,
    downs: 66,
    comment_count: 42,
    view_count: 900,
    awards: [],
    award_total: 0,
    removed: false,
    removal_reason: '',
    removed_by: null,
    deleted_by_author: false,
    locked: false,
    stickied: false,
    nsfw: false,
    spoiler: false,
    edited: false,
    created_at: Date.now() / 1000 - 3600,
    age_label: '1 hr ago',
    generation_state: 'idle',
    user_vote: 0,
    is_own: false,
    saved: false,
    media: null,
    ...overrides,
  };
}

export function makeComment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: 'c1',
    post_id: 'p1',
    parent_id: null,
    subreddit: 'testboard',
    body: 'lmao the confidence',
    author: 'TiredBarnacle79',
    author_id: null,
    author_badge: null,
    depth: 0,
    score: 280,
    ups: 300,
    downs: 20,
    awards: [],
    award_total: 0,
    removed: false,
    removal_reason: '',
    removed_by: null,
    deleted_by_author: false,
    edited: false,
    is_op: false,
    tone: 'funny',
    created_at: Date.now() / 1000 - 600,
    age_label: '10 min ago',
    user_vote: 0,
    is_own: false,
    replies: [],
    hidden_replies: 0,
    ...overrides,
  };
}

export function makeBoard(overrides: Partial<Board> = {}): Board {
  return {
    id: 'b1',
    name: 'testboard',
    kind: 'text',
    title: 'Test Board',
    description: 'a board',
    sidebar: '',
    rules: ['Stay on topic'],
    topics: [],
    nsfw: false,
    color: '#ff4500',
    banner_color: '#0b1416',
    icon: '🔥',
    subscribers: 4200,
    members_online: 12,
    moderators: ['AutoModerator'],
    created_at: 1_700_000_000,
    created_by: null,
    creator_username: null,
    is_official: true,
    allow_user_posts: true,
    moderation_enabled: true,
    post_count: 3,
    subscribed: false,
    can_edit: false,
    ...overrides,
  };
}

export function renderWithRouter(ui: ReactElement) {
  const result = render(<MemoryRouter>{ui}</MemoryRouter>);
  return {
    ...result,
    // Keep the router wrapper on re-render; without it every <Link> throws.
    rerender: (next: ReactElement) => result.rerender(<MemoryRouter>{next}</MemoryRouter>),
  };
}
