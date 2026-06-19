import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams, useNavigationType } from 'react-router-dom'
import '../styles/Search.css'
import '../styles/AdminPage.css'
import ReservationModal from './ReservationModal'
import { apiFetch } from '../api'

const getStorageKey = () => {
  const user = (() => { try { return JSON.parse(localStorage.getItem('user') || '{}') } catch { return {} } })()
  return user.id ? `shelfa-recent-searches-${user.id}` : 'shelfa-recent-searches'
}
interface RecentSearch { keyword: string; category: string }
interface BookResult { id: string; title: string; author: string; publisher: string; shelf_location: string; cover_image_url: string; status: string; displayStatus: string }

const PLACEHOLDER_MAP: Record<string, string> = {
  '전체': '제목, 저자, 키워드 검색', '저자': '저자명을 입력하세요', '출판사': '출판사명을 입력하세요', '분류': '분류명을 입력하세요',
}

function Search() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const navigationType = useNavigationType()
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [searchValue, setSearchValue] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [recentSearches, setRecentSearches] = useState<RecentSearch[]>([])
  const [searchCategory, setSearchCategory] = useState('전체')
  const [showDropdown, setShowDropdown] = useState(false)
  const [lastSearchCategory, setLastSearchCategory] = useState('전체')
  const [searchResults, setSearchResults] = useState<BookResult[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [favoriteBookIds, setFavoriteBookIds] = useState<Set<string>>(new Set())
  const [selectedBook, setSelectedBook] = useState<BookResult | null>(null)
  const myLoanIds = useRef<Set<string>>(new Set())
  const myResIds = useRef<Set<string>>(new Set())
  const [gearOpenId, setGearOpenId] = useState<string | null>(null)
  const [showDevNotice, setShowDevNotice] = useState(false)
  const [favError, setFavError] = useState(false)
  const isAdmin = (() => { try { return JSON.parse(localStorage.getItem('user') || '{}') } catch { return {} } })().role === 'admin'

  useEffect(() => {
    fetchFavorites()
    // 뒤로가기일 때만 검색 상태 복원
    if (navigationType === 'POP') {
      const savedValue = sessionStorage.getItem('search_value')
      const savedCategory = sessionStorage.getItem('search_category') || '전체'
      if (savedValue && !searchParams.get('q')) {
        setSearchValue(savedValue)
        setSearchCategory(savedCategory)
        setLastSearchCategory(savedCategory)
        setIsSearching(true)
        fetchBooks(savedValue, savedCategory)
      }
    } else {
      sessionStorage.removeItem('search_value')
      sessionStorage.removeItem('search_category')
    }
    let saved: string | null = null
    try {
      saved = localStorage.getItem(getStorageKey())
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (typeof parsed[0] === 'string') setRecentSearches(parsed.map((s: string) => ({ keyword: s, category: '전체' })))
          else setRecentSearches(parsed)
        }
      }
    } catch { localStorage.removeItem(getStorageKey()) }
    const q = searchParams.get('q')
    const cat = searchParams.get('cat')
    if (cat) { setSearchCategory(cat); setLastSearchCategory(cat) }
    if (q) {
      setSearchValue(q); setIsSearching(true)
      fetchBooks(q, cat || '전체')
      try {
        const current = saved ? JSON.parse(saved) : []
        const normalized: RecentSearch[] = Array.isArray(current) && current.length > 0 && typeof current[0] === 'string'
          ? current.map((s: string) => ({ keyword: s, category: '전체' })) : current
        const updated = [{ keyword: q, category: cat || '전체' }, ...normalized.filter((s: RecentSearch) => !(s.keyword === q && s.category === (cat || '전체')))].slice(0, 10)
        saveSearches(updated)
      } catch { saveSearches([{ keyword: q, category: cat || '전체' }]) }
    }
  }, [searchParams])

  const fetchFavorites = async () => {
    setFavError(false)
    try {
      const [favRes, loanRes, resRes] = await Promise.all([
        apiFetch('/favorites/me?limit=100'),
        apiFetch('/loans/me?limit=50'),
        apiFetch('/reservations/me?limit=50'),
      ])
      if (favRes.ok) {
        const data = await favRes.json()
        setFavoriteBookIds(new Set(data.items?.map((f: any) => f.book.id) || []))
      }
      if (loanRes.ok) {
        const data = await loanRes.json()
        myLoanIds.current = new Set(data.items?.map((l: any) => l.book.id) || [])
      }
      if (resRes.ok) {
        const data = await resRes.json()
        myResIds.current = new Set(data.items?.filter((r: any) => r.status === 'PENDING').map((r: any) => r.book.id) || [])
      }
    } catch { setFavError(true) }
  }

  const fetchBooks = async (keyword: string, category?: string) => {
    sessionStorage.setItem('search_value', keyword)
    const resolvedCategory = category ?? searchCategory
    sessionStorage.setItem('search_category', resolvedCategory)
    try {
      const res = await apiFetch(`/books/search?query=${encodeURIComponent(keyword)}&limit=50`)
      if (!res.ok) { setSearchResults([]); return }
      const data = await res.json()
      const items = (data.items || []).map((book: any) => {
        let displayStatus = book.status === 'AVAILABLE' ? 'available' : 'borrowed'
        if (myLoanIds.current.has(book.id)) displayStatus = 'my_loan'
        else if (myResIds.current.has(book.id)) displayStatus = 'my_reservation'
        return { ...book, displayStatus }
      })
      setSearchResults(items)
    } catch { alert('검색 중 오류가 발생했습니다.'); setSearchResults([]) }
  }

  const saveSearches = (searches: RecentSearch[]) => { setRecentSearches(searches); localStorage.setItem(getStorageKey(), JSON.stringify(searches)) }
  const handleSearch = () => {
    const trimmed = searchValue.trim()
    if (!trimmed) return
    const updated = [{ keyword: trimmed, category: searchCategory }, ...recentSearches.filter(s => !(s.keyword === trimmed && s.category === searchCategory))].slice(0, 10)
    saveSearches(updated); setIsSearching(true); setLastSearchCategory(searchCategory); setIsFocused(false); setShowDropdown(false)
    searchInputRef.current?.blur(); fetchBooks(trimmed)
  }
  const handleDeleteOne = (item: RecentSearch) => { saveSearches(recentSearches.filter(s => !(s.keyword === item.keyword && s.category === item.category))) }
  const handleDeleteAll = () => { saveSearches([]) }
  const handleRecentClick = (item: RecentSearch) => {
    setSearchValue(item.keyword); setSearchCategory(item.category); setLastSearchCategory(item.category)
    saveSearches([item, ...recentSearches.filter(s => !(s.keyword === item.keyword && s.category === item.category))])
    setIsSearching(true); setIsFocused(false); fetchBooks(item.keyword)
  }

  const handleToggleFavorite = async (bookId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (isProcessing) return
    setIsProcessing(true)
    try {
      if (favoriteBookIds.has(bookId)) {
        await apiFetch(`/favorites/${bookId}`, { method: 'DELETE' })
        setFavoriteBookIds(prev => { const s = new Set(prev); s.delete(bookId); return s })
      } else {
        await apiFetch(`/favorites/${bookId}`, { method: 'POST' })
        setFavoriteBookIds(prev => new Set(prev).add(bookId))
      }
    } catch { alert('오류가 발생했습니다.') } finally { setIsProcessing(false) }
  }

  const getCategoryLabel = (cat: string) => {
    const map: Record<string, string> = { '전체': '전체', '저자': '작가', '출판사': '출판사', '분류': '분류' }
    return map[cat] || cat
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg>
        <span className="logo-text">XYZ 도서관</span>
        {(() => { try { return JSON.parse(localStorage.getItem('user') || '{}') } catch { return {} } })().role === 'admin' && (
          <button className="admin-nav-btn" onClick={() => navigate('/admin')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
          </button>
        )}
      </div>
      <div className="search-content">
        <div className="search-input-section">
          <div className="search-input-bar">
            <div className="search-bar-dropdown" onClick={() => setShowDropdown(!showDropdown)}>
              <span className="search-bar-dropdown-text">{searchCategory}</span>
              <span className="search-bar-dropdown-arrow">▼</span>
              {showDropdown && (<div className="search-bar-dropdown-menu">
                {['전체', '저자', '출판사', '분류'].map(cat => (
                  <div key={cat} className={`search-bar-dropdown-item${searchCategory === cat ? ' active' : ''}`}
                    onClick={(e) => { e.stopPropagation(); setSearchCategory(cat); setShowDropdown(false) }}>{cat}</div>
                ))}
              </div>)}
            </div>
            <input ref={searchInputRef} className="search-input-field" type="text"
              placeholder={PLACEHOLDER_MAP[searchCategory] || '검색어를 입력하세요'} value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleSearch() }}
              onFocus={() => { setIsFocused(true); setIsSearching(false) }} />
            <svg className="search-bar-icon-btn" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" onClick={handleSearch}>
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
        </div>
        {favError && (
          <div className="search-error-row">오류가 발생했습니다. <button className="refresh-btn" onClick={fetchFavorites}>↺</button></div>
        )}
        {isSearching ? (
          <div className="search-result-section">
            <div className="search-result-summary">
              '<span className="search-result-highlight">{lastSearchCategory} : {searchValue}</span>'에 대한 검색결과 총 <span className="search-result-highlight">{searchResults.length}</span>건
            </div>
            {searchResults.length === 0 ? <div className="search-result-empty">검색 결과가 없습니다.</div> : (
              <div className="search-result-list">{searchResults.map(book => (
                <div className="search-result-card" key={book.id}>
                  <div className="search-result-card-body" onClick={() => navigate(`/book/${book.id}`)}>
                    <div className="search-result-cover">
                      {book.cover_image_url ? <img src={book.cover_image_url} alt={book.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : <div className="search-result-cover-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div>}
                    </div>
                    <div className="search-result-info">
                      <div className="search-result-title-row">
                        <div className="search-result-title">{book.title}</div>
                        <button className="search-result-fav-btn" onClick={(e) => handleToggleFavorite(book.id, e)}>
                          <svg viewBox="0 0 24 24" fill={favoriteBookIds.has(book.id) ? '#E03131' : 'none'} stroke={favoriteBookIds.has(book.id) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                          </svg>
                        </button>
                      </div>
                      <div className="search-result-meta">{book.shelf_location}</div>
                      <div className="search-result-meta">{book.author} 지음</div>
                      <div className="search-result-meta">{book.publisher}</div>
                      <div className="search-result-bottom">
                        {book.displayStatus === 'available' && (<><span className="badge-available">대출가능</span><button className="search-result-reserve-btn" onClick={(e) => { e.stopPropagation(); setSelectedBook(book) }}>예약하기</button></>)}
                        {(book.displayStatus === 'borrowed' || book.displayStatus === 'my_loan') && (<><span className="badge-unavailable">대출불가</span><button className="search-result-reserve-btn disabled" disabled onClick={(e) => e.stopPropagation()}>예약불가</button></>)}
                        {book.displayStatus === 'my_reservation' && (<><span className="badge-myreserve">예약완료</span><button className="search-result-reserve-btn disabled" disabled onClick={(e) => e.stopPropagation()}>예약완료</button></>)}
                      </div>
                    </div>
                  </div>
                  {isAdmin && (
                    <div className="search-result-card-btns">
                      <div className="admin-gear-wrap">
                        <button className="admin-gear-btn" onClick={() => setGearOpenId(gearOpenId === book.id ? null : book.id)}>
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="12" cy="12" r="3" />
                            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                          </svg>
                        </button>
                        {gearOpenId === book.id && (
                          <div className="admin-gear-dropdown" style={{ bottom: '24px', top: 'auto' }}>
                            <button className="admin-gear-item" onClick={() => { setGearOpenId(null); setShowDevNotice(true) }}>도서 정보 수정</button>
                            <button className="admin-gear-item admin-gear-item--danger" onClick={() => { setGearOpenId(null); setShowDevNotice(true) }}>도서 삭제</button>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}</div>
            )}
          </div>
        ) : isFocused && (
          <div className="search-recent">
            <div className="search-recent-header">
              <span className="search-recent-title">최근 검색어</span>
              {recentSearches.length > 0 && <button className="search-recent-clear" onClick={handleDeleteAll}>전체삭제</button>}
            </div>
            {recentSearches.length === 0 ? <div className="search-recent-empty">최근 검색어가 없습니다.</div> : (
              <div className="search-recent-tags">{recentSearches.map((item, idx) => (
                <div className="search-recent-tag" key={`${item.category}-${item.keyword}-${idx}`}>
                  <span onClick={() => handleRecentClick(item)}>{getCategoryLabel(item.category)} : {item.keyword}</span>
                  <button className="search-recent-tag-delete" onClick={() => handleDeleteOne(item)}>×</button>
                </div>
              ))}</div>
            )}
          </div>
        )}
      </div>

      {showDevNotice && (
        <div className="modal-overlay" onClick={() => setShowDevNotice(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={() => setShowDevNotice(false)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
            <div className="modal-result">
              <div className="modal-result-icon"><svg viewBox="0 0 24 24" fill="none" stroke="#aaa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg></div>
              <p className="modal-result-text">추후 개발 예정입니다.</p>
              <button className="modal-btn-outline" onClick={() => setShowDevNotice(false)}>확인</button>
            </div>
          </div>
        </div>
      )}

      {selectedBook && (
        <ReservationModal
          bookId={selectedBook.id}
          title={selectedBook.title}
          author={selectedBook.author}
          classNumber={selectedBook.shelf_location || ''}
          badgeLabel="대출가능"
          badgeClass="badge-available"
          onClose={() => setSelectedBook(null)}
          onSuccess={() => { setSelectedBook(null); fetchBooks(searchValue) }}
        />
      )}

      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item active" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}
export default Search
