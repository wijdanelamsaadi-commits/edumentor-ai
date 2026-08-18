import { Navigate, Route, Routes } from 'react-router-dom'
import './App.css'
import AppLayout from './components/AppLayout.jsx'
import ProfessorRoute from './components/ProfessorRoute.jsx'
import StudentRoute from './components/StudentRoute.jsx'
import ParentRoute from './components/ParentRoute.jsx'
import { AuthProvider } from './context/AuthContext.jsx'
import { LearningProvider } from './context/LearningContext.jsx'
import { ThemeProvider } from './context/ThemeContext.jsx'
import { UserDataProvider } from './context/UserDataContext.jsx'
import AdminRoute from './components/AdminRoute.jsx'
import AdminAuditPage from './pages/AdminAuditPage.jsx'
import AdminCoursesPage from './pages/AdminCoursesPage.jsx'
import AdminDashboardPage from './pages/AdminDashboardPage.jsx'
import AdminDiagnosticPage from './pages/AdminDiagnosticPage.jsx'
import AdminRagPage from './pages/AdminRagPage.jsx'
import AdminStatisticsPage from './pages/AdminStatisticsPage.jsx'
import AdminSubjectsPage from './pages/AdminSubjectsPage.jsx'
import AdminUsersPage from './pages/AdminUsersPage.jsx'
import AssessmentResultPage from './pages/AssessmentResultPage.jsx'
import AssessmentTakePage from './pages/AssessmentTakePage.jsx'
import AssessmentsPage from './pages/AssessmentsPage.jsx'
import ChatbotPage from './pages/ChatbotPage.jsx'
import CourseDetailPage from './pages/CourseDetailPage.jsx'
import CoursesPage from './pages/CoursesPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import DiagnosticPage from './pages/DiagnosticPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import ProfessorAnalyticsPage from './pages/ProfessorAnalyticsPage.jsx'
import ProfessorAutomaticCourseImportPage from './pages/ProfessorAutomaticCourseImportPage.jsx'
import ProfessorAssessmentEditorPage from './pages/ProfessorAssessmentEditorPage.jsx'
import ProfessorAssessmentResultsPage from './pages/ProfessorAssessmentResultsPage.jsx'
import ProfessorAssessmentsPage from './pages/ProfessorAssessmentsPage.jsx'
import ProfessorClassroomDetailPage from './pages/ProfessorClassroomDetailPage.jsx'
import ProfessorClassroomFormPage from './pages/ProfessorClassroomFormPage.jsx'
import ProfessorClassroomsPage from './pages/ProfessorClassroomsPage.jsx'
import ProfessorCoursesPage from './pages/ProfessorCoursesPage.jsx'
import ProfessorCourseStudentsPage from './pages/ProfessorCourseStudentsPage.jsx'
import ProfessorCourseViewPage from './pages/ProfessorCourseViewPage.jsx'
import ProfessorDashboardPage from './pages/ProfessorDashboardPage.jsx'
import ProfessorRemediationPage from './pages/ProfessorRemediationPage.jsx'
import ProfessorStudyPathPage from './pages/ProfessorStudyPathPage.jsx'
import ProfessorStudentDetailPage from './pages/ProfessorStudentDetailPage.jsx'
import ProfilePage from './pages/ProfilePage.jsx'
import ParentDashboardPage from './pages/ParentDashboardPage.jsx'
import ParentStudentDetailPage from './pages/ParentStudentDetailPage.jsx'
import QuizPage from './pages/QuizPage.jsx'
import RegisterPage from './pages/RegisterPage.jsx'
import ResourcesPage from './pages/ResourcesPage.jsx'
import RegionalExamDetailPage from './pages/RegionalExamDetailPage.jsx'
import RegionalExamPreparationPage from './pages/RegionalExamPreparationPage.jsx'
import RemediationPage from './pages/RemediationPage.jsx'
import RemediationComparisonPage from './pages/RemediationComparisonPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import PersonalizedLessonPage from './pages/PersonalizedLessonPage.jsx'
import StudyPathPage from './pages/StudyPathPage.jsx'

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
              <Route path="/admin/subjects" element={<AdminSubjectsPage />} />
              <Route path="/admin/diagnostic" element={<AdminDiagnosticPage />} />
              <Route path="/admin/courses" element={<AdminCoursesPage />} />
              <Route path="/admin/statistics" element={<AdminStatisticsPage />} />
              <Route path="/admin/rag" element={<AdminRagPage />} />
              <Route path="/admin/audit" element={<AdminAuditPage />} />
            </Route>
            <Route element={<ProfessorRoute><AppLayout /></ProfessorRoute>}>
              <Route path="/professor" element={<ProfessorDashboardPage />} />
              <Route path="/professor/courses" element={<ProfessorCoursesPage />} />
              <Route path="/professor/courses/automatic-import" element={<ProfessorAutomaticCourseImportPage />} />
              <Route path="/professor/courses/new" element={<Navigate to="/professor/courses/automatic-import" replace />} />
              <Route path="/professor/courses/:id" element={<ProfessorCourseViewPage />} />
              <Route path="/professor/courses/:id/edit" element={<Navigate to="/professor/courses/automatic-import" replace />} />
              <Route path="/professor/courses/:id/content" element={<Navigate to="/professor/courses/automatic-import" replace />} />
              <Route path="/professor/courses/:id/quiz" element={<Navigate to="/professor/courses" replace />} />
              <Route path="/professor/courses/:id/students" element={<ProfessorCourseStudentsPage />} />
              <Route path="/professor/classrooms" element={<ProfessorClassroomsPage />} />
              <Route path="/professor/classrooms/new" element={<ProfessorClassroomFormPage />} />
              <Route path="/professor/classrooms/:id" element={<ProfessorClassroomDetailPage />} />
              <Route path="/professor/students/:studentId" element={<ProfessorStudentDetailPage />} />
              <Route path="/professor/assessments" element={<ProfessorAssessmentsPage />} />
              <Route path="/professor/assessments/new" element={<ProfessorAssessmentEditorPage />} />
              <Route path="/professor/assessments/:id/edit" element={<ProfessorAssessmentEditorPage />} />
              <Route path="/professor/assessments/:id/results" element={<ProfessorAssessmentResultsPage />} />
              <Route path="/professor/remediation" element={<ProfessorRemediationPage />} />
              <Route path="/professor/study-paths/:pathId" element={<ProfessorStudyPathPage />} />
              <Route path="/professor/analytics" element={<ProfessorAnalyticsPage />} />
              <Route path="/professor/profile" element={<ProfilePage />} />
              <Route path="/professor/settings" element={<SettingsPage />} />
            </Route>
            <Route element={<StudentRoute><AppLayout /></StudentRoute>}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/diagnostic" element={<DiagnosticPage />} />
              <Route path="/courses" element={<CoursesPage />} />
              <Route path="/courses/:id" element={<CourseDetailPage />} />
              <Route path="/quiz/:id" element={<QuizPage />} />
              <Route path="/assessments" element={<AssessmentsPage />} />
              <Route path="/assessments/:id" element={<AssessmentTakePage />} />
              <Route path="/assessment-results/:attemptId" element={<AssessmentResultPage />} />
              <Route path="/remediation/:planId" element={<RemediationPage />} />
              <Route path="/remediation/:planId/comparison" element={<RemediationComparisonPage />} />
              <Route path="/study-paths/:pathId" element={<StudyPathPage />} />
              <Route path="/personalized-lessons/:id" element={<PersonalizedLessonPage />} />
              <Route path="/chatbot" element={<ChatbotPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/resources" element={<ResourcesPage />} />
              <Route path="/regional-exam-preparation" element={<RegionalExamPreparationPage />} />
              <Route path="/regional-exam-preparation/:examId" element={<RegionalExamDetailPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
            <Route element={<ParentRoute><AppLayout /></ParentRoute>}>
              <Route path="/parent" element={<Navigate to="/parent/dashboard" replace />} />
              <Route path="/parent/dashboard" element={<ParentDashboardPage />} />
              <Route path="/parent/progress" element={<ParentDashboardPage section="progress" />} />
              <Route path="/parent/results" element={<ParentDashboardPage section="results" />} />
              <Route path="/parent/weaknesses" element={<ParentDashboardPage section="weaknesses" />} />
              <Route path="/parent/regional-exams" element={<ParentDashboardPage section="regional" />} />
              <Route path="/parent/students/:studentId" element={<ParentStudentDetailPage />} />
              <Route path="/parent/settings" element={<SettingsPage />} />
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
