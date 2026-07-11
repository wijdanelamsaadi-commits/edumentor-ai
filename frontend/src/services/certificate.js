export function buildCertificateEligibility({ courses, progress, quizResults }) {
  const availableCourses = Array.isArray(courses) ? courses : []
  const completedCourses = availableCourses.filter((course) => Number(progress?.[course.id]?.progress || 0) >= 100)
  const finalCourse = [...availableCourses].sort((first, second) => (
    Number(first.display_order || first.id) - Number(second.display_order || second.id)
  )).at(-1)
  const finalQuiz = finalCourse ? quizResults?.[finalCourse.id] : null
  const finalScore = Number(finalQuiz?.score || 0)
  const allCoursesCompleted = availableCourses.length > 0 && completedCourses.length === availableCourses.length
  const finalQuizPassed = Boolean(finalCourse && finalQuiz && finalScore >= 70)

  return {
    allCoursesCompleted,
    completedCourses: completedCourses.length,
    finalCourse,
    finalQuizPassed,
    finalScore,
    isEligible: allCoursesCompleted && finalQuizPassed,
    totalCourses: availableCourses.length,
  }
}

export async function generateCertificatePdf({
  email,
  finalScore,
  fullName,
  level,
}) {
  const { jsPDF } = await import('jspdf')
  const certificateId = createCertificateId(email)
  const awardedAt = new Date()
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
  const width = doc.internal.pageSize.getWidth()
  const height = doc.internal.pageSize.getHeight()

  doc.setFillColor(255, 255, 255)
  doc.rect(0, 0, width, height, 'F')

  doc.setDrawColor(229, 57, 53)
  doc.setLineWidth(1.2)
  doc.rect(12, 12, width - 24, height - 24)
  doc.setLineWidth(0.35)
  doc.rect(18, 18, width - 36, height - 36)

  doc.setTextColor(229, 57, 53)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(28)
  doc.text('EduMentor AI', width / 2, 34, { align: 'center' })

  doc.setTextColor(17, 24, 39)
  doc.setFontSize(15)
  doc.setFont('helvetica', 'normal')
  doc.text("Certificat officiel d'achevement", width / 2, 46, { align: 'center' })

  doc.setDrawColor(229, 57, 53)
  doc.line(78, 54, width - 78, 54)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(13)
  doc.text('Ce certificat est decerne a', width / 2, 72, { align: 'center' })

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(30)
  doc.setTextColor(229, 57, 53)
  doc.text(fullName || 'Apprenant EduMentor', width / 2, 88, { align: 'center' })

  doc.setTextColor(17, 24, 39)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(13)
  doc.text(email || 'Email non renseigne', width / 2, 99, { align: 'center' })

  doc.setFontSize(14)
  doc.text(
    "Pour avoir termine l'ensemble du parcours EduMentor AI et reussi le quiz final.",
    width / 2,
    116,
    { align: 'center' },
  )
  doc.text(
    "Felicitations pour votre progression, votre perseverance et vos competences acquises en intelligence artificielle.",
    width / 2,
    126,
    { align: 'center' },
  )

  const infoY = 147
  drawInfoBlock(doc, 48, infoY, 'Niveau atteint', level || 'Non defini')
  drawInfoBlock(doc, 116, infoY, "Date d'obtention", formatDate(awardedAt))
  drawInfoBlock(doc, 184, infoY, 'Score final', `${finalScore}%`)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(17, 24, 39)
  doc.text('Signature', 52, 184)
  doc.setDrawColor(229, 57, 53)
  doc.line(52, 178, 116, 178)
  doc.setFont('helvetica', 'italic')
  doc.setFontSize(16)
  doc.text('Equipe EduMentor AI', 52, 174)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  doc.setTextColor(105, 112, 125)
  doc.text(`Identifiant unique du certificat : ${certificateId}`, width - 52, 181, { align: 'right' })

  doc.save(`certificat-edumentor-ai-${certificateId}.pdf`)
}

function drawInfoBlock(doc, x, y, label, value) {
  doc.setDrawColor(229, 57, 53)
  doc.setLineWidth(0.35)
  doc.roundedRect(x, y, 50, 24, 2, 2)
  doc.setTextColor(105, 112, 125)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.text(label, x + 25, y + 8, { align: 'center' })
  doc.setTextColor(17, 24, 39)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.text(String(value), x + 25, y + 17, { align: 'center' })
}

function createCertificateId(email) {
  const cleanEmail = String(email || 'edumentor').toLowerCase()
  let hash = 0
  for (let index = 0; index < cleanEmail.length; index += 1) {
    hash = ((hash << 5) - hash) + cleanEmail.charCodeAt(index)
    hash |= 0
  }
  return `EDU-${new Date().getFullYear()}-${Math.abs(hash).toString(16).toUpperCase().padStart(8, '0')}`
}

function formatDate(date) {
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  }).format(date)
}
