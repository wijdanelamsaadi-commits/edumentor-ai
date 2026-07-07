function PageTitle({ title, subtitle }) {
  return (
    <div className="page-title">
      <span className="eyebrow">EduMentor AI</span>
      <h2>{title}</h2>
      <p>{subtitle}</p>
    </div>
  )
}

export default PageTitle
