export type AuthorBadge = { kind: string; label: string; title: string } | null;

export interface Award {
  id: string;
  name: string;
  icon: string;
  cost: number;
  color: string;
  description: string;
  rarity: string;
  count?: number;
}

export interface Media {
  id: string;
  url: string;
  thumb_url: string;
  width: number;
  height: number;
  aspect_ratio: number;
  source_url: string;
  source_page: string;
  source_site: string;
  analysis_state: 'pending' | 'done' | 'failed';
  caption: string;
  tags: string[];
  nsfw: boolean;
}

export interface ImageAnalysis {
  caption: string;
  detailed_description: string;
  visible_text: string;
  subject_type: string;
  tags: string[];
  mood: string;
  technical_notes: string;
  discussion_hooks: string[];
  suggested_titles: string[];
  nsfw: boolean;
  depicts_identifiable_person: boolean;
}

export interface Post {
  id: string;
  subreddit: string;
  title: string;
  body: string;
  kind: 'text' | 'link' | 'image';
  link_url: string;
  flair: string;
  author: string;
  author_id: string | null;
  author_badge: AuthorBadge;
  score: number;
  ups: number;
  downs: number;
  comment_count: number;
  view_count: number;
  awards: Award[];
  award_total: number;
  removed: boolean;
  removal_reason: string;
  removed_by: string | null;
  deleted_by_author: boolean;
  locked: boolean;
  stickied: boolean;
  nsfw: boolean;
  spoiler: boolean;
  edited: boolean;
  created_at: number;
  age_label: string;
  generation_state: string;
  user_vote: number;
  is_own: boolean;
  saved: boolean;
  media: Media | null;
}

export interface Comment {
  id: string;
  post_id: string;
  parent_id: string | null;
  subreddit: string;
  body: string;
  author: string;
  author_id: string | null;
  author_badge: AuthorBadge;
  depth: number;
  score: number;
  ups: number;
  downs: number;
  awards: Award[];
  award_total: number;
  removed: boolean;
  removal_reason: string;
  removed_by: string | null;
  deleted_by_author: boolean;
  edited: boolean;
  is_op: boolean;
  tone: string;
  created_at: number;
  age_label: string;
  user_vote: number;
  is_own: boolean;
  replies: Comment[];
  hidden_replies: number;
}

export interface Board {
  id: string;
  name: string;
  kind: 'text' | 'photo';
  title: string;
  description: string;
  sidebar: string;
  rules: string[];
  topics: string[];
  nsfw: boolean;
  color: string;
  banner_color: string;
  icon: string;
  subscribers: number;
  members_online: number;
  moderators: string[];
  created_at: number;
  created_by: string | null;
  creator_username: string | null;
  is_official: boolean;
  allow_user_posts: boolean;
  moderation_enabled: boolean;
  post_count: number;
  subscribed: boolean;
  can_edit: boolean;
  personal_prompt?: string;
  custom_prompt?: string;
  override_global?: boolean;
  overrides?: Record<string, number | string | null>;
  activity_level?: number;
}

export interface Preferences {
  theme: 'dark' | 'light';
  compact_mode: boolean;
  feed_sort: string;
  show_nsfw: boolean;
  blur_nsfw: boolean;
  live_updates: boolean;
  auto_generate_on_open: boolean;
  comment_density_override: string | null;
  content_intensity: number | null;
  humor_override: number | null;
  hide_removed: boolean;
  show_human_badges: boolean;
  open_links_in_new_tab: boolean;
  notification_replies: boolean;
  language_style: string;
  content_font_size: number;
  content_font_family: string;
}

export interface User {
  id: string;
  username: string;
  display_name: string;
  bio: string;
  avatar_color: string;
  avatar_emoji: string;
  banner_color: string;
  karma: { post: number; comment: number; awarder?: number };
  is_guest: boolean;
  is_admin: boolean;
  kind: 'human' | 'ai';
  created_at: number;
  awards_received: Record<string, number>;
  email?: string | null;
  coins?: number;
  subscriptions?: string[];
  interests?: string[];
  banned_subreddits?: string[];
  preferences?: Preferences;
  personal_prompt?: string;
  wiped_at?: number | null;
}

export interface SiteInfo {
  name: string;
  description: string;
  user: User | null;
  is_admin: boolean;
  simulation: { enabled: boolean; background: boolean; tick_seconds: number };
  counts: Record<string, number>;
  llm_ready: boolean;
}

export interface Notification {
  _id: string;
  kind: string;
  title: string;
  body: string;
  subreddit: string;
  post_id: string | null;
  comment_id: string | null;
  actor: string;
  read: boolean;
  at: number;
}

export interface WorldConfig {
  global_prompt: string;
  style_prompt: string;
  site_description: string;
  serious_mode: boolean;
  humor: number;
  toxicity: number;
  argument_rate: number;
  wholesomeness: number;
  shitpost_rate: number;
  expertise: number;
  comment_density: string;
  thread_depth: number;
  allow_nsfw: boolean;
  moderation_enabled: boolean;
  moderation_strictness: number;
  removal_rate: number;
  award_rate: number;
  user_vote_bonus: number;
  vote_volatility: number;
  simulation_enabled: boolean;
  background_activity: boolean;
  tick_seconds: number;
  max_comments_per_thread: number;
  posts_per_board_target: number;
  [key: string]: unknown;
}

export interface LLMConnection {
  id: string;
  name: string;
  provider_type: string;
  base_url: string;
  models: string[];
  enabled: boolean;
  weight: number;
  api_key_preview: string;
  has_api_key: boolean;
}

export interface LLMConfig {
  connections: LLMConnection[];
  roles: Record<
    string,
    { connection_id: string | null; model: string; temperature: number; max_tokens: number }
  >;
  fallback_to_mock: boolean;
  multi_model_mixing: boolean;
  default_connection_id: string | null;
}
