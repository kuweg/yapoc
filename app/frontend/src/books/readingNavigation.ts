import {useAppStore} from '../store/appStore'

export function openBookSource(book_id: string, number?: number) {
  window.dispatchEvent(new CustomEvent('yapoc:open-book', {detail: {book_id, number}}))
  useAppStore.getState().setActiveTab('books')
}
