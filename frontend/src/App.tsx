import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { AdminPage } from './pages/AdminPage';
import { AuthPage } from './pages/AuthPage';
import { BoardPage } from './pages/BoardPage';
import { FeedPage } from './pages/FeedPage';
import { SettingsPage } from './pages/SettingsPage';
import { ThreadPage } from './pages/ThreadPage';
import {
  BoardsPage,
  InboxPage,
  NotFoundPage,
  ProfilePage,
  SavedPage,
  SearchPage,
  SubmitPage,
} from './pages/misc';

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<FeedPage scope="home" />} />
        <Route path="/popular" element={<FeedPage scope="popular" />} />
        <Route path="/boards" element={<BoardsPage />} />
        <Route path="/r/:name" element={<BoardPage />} />
        <Route path="/r/:name/comments/:postId" element={<ThreadPage />} />
        <Route path="/comments/:postId" element={<ThreadPage />} />
        <Route path="/u/:username" element={<ProfilePage />} />
        <Route path="/user/:username" element={<ProfilePage />} />
        <Route path="/submit" element={<SubmitPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/saved" element={<SavedPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/signup" element={<Navigate to="/register" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
