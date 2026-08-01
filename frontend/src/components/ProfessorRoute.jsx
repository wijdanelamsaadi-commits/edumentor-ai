import RequireRole from './RequireRole.jsx'

function ProfessorRoute({ children }) {
  return (
    <RequireRole allowedRoles={['professor', 'admin']} fallback="/dashboard">
      {children}
    </RequireRole>
  )
}

export default ProfessorRoute
