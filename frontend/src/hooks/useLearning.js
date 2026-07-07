import { useContext } from 'react'
import { LearningContext } from '../context/learningContext.js'

export function useLearning() {
  const context = useContext(LearningContext)

  if (!context) {
    throw new Error('useLearning must be used inside LearningProvider')
  }

  return context
}
