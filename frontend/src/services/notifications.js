import {
  createNotification as createBackendNotification,
  deleteNotification as deleteBackendNotification,
  getNotifications as getBackendNotifications,
  markNotificationRead as markBackendNotificationRead,
} from './api.js'

export const NOTIFICATIONS_STORAGE_KEY = 'edumentor:notifications'
export const NOTIFICATIONS_UPDATED_EVENT = 'edumentor:notificationsUpdated'
export const NOTIFICATION_PREFERENCES_STORAGE_KEY = 'edumentor:notificationPreferences'

const DEFAULT_NOTIFICATION_PREFERENCES = {
  chatbot: true,
  pdf: true,
  progress: true,
  quiz: true,
  chapters: true,
}

export function getNotifications() {
  try {
    const storedNotifications = localStorage.getItem(NOTIFICATIONS_STORAGE_KEY)
    const notifications = storedNotifications ? JSON.parse(storedNotifications) : []
    return Array.isArray(notifications) ? sortNotifications(notifications) : []
  } catch {
    return []
  }
}

export async function loadNotifications() {
  const localNotifications = getNotifications()

  try {
    const backendNotifications = await getBackendNotifications()
    const mergedNotifications = mergeNotifications(
      normalizeBackendNotifications(backendNotifications),
      localNotifications,
    )
    saveNotifications(mergedNotifications, { silent: true })
    return mergedNotifications
  } catch {
    return localNotifications
  }
}

export function addNotification({ message, title, type }) {
  if (!isNotificationTypeEnabled(type)) {
    return null
  }

  const notification = {
    id: createNotificationId(),
    type,
    title,
    message,
    date: new Date().toISOString(),
    read: false,
  }

  saveNotifications([notification, ...getNotifications()])
  createBackendNotification({
    id: notification.id,
    type: notification.type,
    title: notification.title,
    message: notification.message,
    read: notification.read,
  }).catch(() => {})

  return notification
}

export function getNotificationPreferences() {
  try {
    const storedPreferences = localStorage.getItem(NOTIFICATION_PREFERENCES_STORAGE_KEY)
    return { ...DEFAULT_NOTIFICATION_PREFERENCES, ...(storedPreferences ? JSON.parse(storedPreferences) : {}) }
  } catch {
    return DEFAULT_NOTIFICATION_PREFERENCES
  }
}

export function saveNotificationPreferences(preferences) {
  localStorage.setItem(
    NOTIFICATION_PREFERENCES_STORAGE_KEY,
    JSON.stringify({ ...DEFAULT_NOTIFICATION_PREFERENCES, ...preferences }),
  )
}

export function markNotificationAsRead(notificationId) {
  saveNotifications(getNotifications().map((notification) => (
    notification.id === notificationId ? { ...notification, read: true } : notification
  )))
  markBackendNotificationRead(notificationId).catch(() => {})
}

export function markAllNotificationsAsRead() {
  const notifications = getNotifications()
  saveNotifications(notifications.map((notification) => ({ ...notification, read: true })))
  notifications
    .filter((notification) => !notification.read)
    .forEach((notification) => {
      markBackendNotificationRead(notification.id).catch(() => {})
    })
}

export function deleteNotification(notificationId) {
  saveNotifications(getNotifications().filter((notification) => notification.id !== notificationId))
  deleteBackendNotification(notificationId).catch(() => {})
}

export function clearNotifications() {
  const notifications = getNotifications()
  saveNotifications([])
  notifications.forEach((notification) => {
    deleteBackendNotification(notification.id).catch(() => {})
  })
}

function saveNotifications(notifications, options = {}) {
  localStorage.setItem(NOTIFICATIONS_STORAGE_KEY, JSON.stringify(sortNotifications(notifications)))
  if (!options.silent) {
    window.dispatchEvent(new Event(NOTIFICATIONS_UPDATED_EVENT))
  }
}

function sortNotifications(notifications) {
  return [...notifications].sort((first, second) => new Date(second.date) - new Date(first.date))
}

function normalizeBackendNotifications(notifications) {
  if (!Array.isArray(notifications)) {
    return []
  }

  return notifications.map((notification) => ({
    id: notification.id,
    type: notification.type,
    title: notification.title,
    message: notification.message,
    date: notification.created_at || notification.date || new Date().toISOString(),
    read: notification.read === true,
  }))
}

function mergeNotifications(primaryNotifications, fallbackNotifications) {
  const notificationMap = new Map()

  fallbackNotifications.forEach((notification) => {
    notificationMap.set(notification.id, notification)
  })
  primaryNotifications.forEach((notification) => {
    notificationMap.set(notification.id, notification)
  })

  return sortNotifications([...notificationMap.values()])
}

function createNotificationId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID()
  }

  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function isNotificationTypeEnabled(type) {
  const preferences = getNotificationPreferences()
  const mappedType = {
    diagnostic: 'progress',
    profile: 'progress',
  }[type] || type
  return preferences[mappedType] !== false
}
