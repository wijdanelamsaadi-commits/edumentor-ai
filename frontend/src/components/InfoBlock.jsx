function InfoBlock({ title, items }) {
  return (
    <article className="info-block">
      <h3>{title}</h3>
      {items.map((item) => (
        <p key={item}>{item}</p>
      ))}
    </article>
  )
}

export default InfoBlock
