import { Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import AppLayout from './components/AppLayout.jsx'
import UserRoute from './components/UserRoute.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { LearningProvider } from './context/LearningContext.jsx'
import { ThemeProvider } from './context/ThemeContext.jsx'
import { UserDataProvider } from './context/UserDataContext.jsx'
import AdminRoute from './components/AdminRoute.jsx'
import AdminAuditPage from './pages/AdminAuditPage.jsx'
import AdminCoursesPage from './pages/AdminCoursesPage.jsx'
import AdminDashboardPage from './pages/AdminDashboardPage.jsx'
import AdminRagPage from './pages/AdminRagPage.jsx'
import AdminStatisticsPage from './pages/AdminStatisticsPage.jsx'
import AdminUsersPage from './pages/AdminUsersPage.jsx'
import ChatbotPage from './pages/ChatbotPage.jsx'
import CourseDetailPage from './pages/CourseDetailPage.jsx'
import CoursesPage from './pages/CoursesPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import DiagnosticPage from './pages/DiagnosticPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import ProfilePage from './pages/ProfilePage.jsx'
import QuizPage from './pages/QuizPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import ResourcesPage from './pages/ResourcesPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <UserDataProvider>
          <LearningProvider>
          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route element={<AdminRoute><AppLayout /></AdminRoute>}>
              <Route path="/admin" element={<AdminDashboardPage />} />
              <Route path="/admin/users" element={<AdminUsersPage />} />
              <Route path="/admin/courses" element={<AdminCoursesPage />} />
              <Route path="/admin/statistics" element={<AdminStatisticsPage />} />
              <Route path="/admin/rag" element={<AdminRagPage />} />
              <Route path="/admin/audit" element={<AdminAuditPage />} />
            </Route>
            <Route element={<UserRoute><AppLayout /></UserRoute>}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/diagnostic" element={<DiagnosticPage />} />
              <Route path="/courses" element={<CoursesPage />} />
              <Route path="/courses/:id" element={<CourseDetailPage />} />
              <Route path="/quiz/:id" element={<QuizPage />} />
              <Route path="/chatbot" element={<ChatbotPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/resources" element={<ResourcesPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/login" replace />} />
          </Routes>
          </LearningProvider>
        </UserDataProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}

export default App
