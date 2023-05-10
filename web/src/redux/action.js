export const showAllRobots = (data) => {
  return ({
    type: 'SHOW_ROBOTS',
    payload: data
  }
  )
}
export const materialType = (data) => {
  return ({
    type: 'SEARCH_MATERIALS',
    payload: data,
  })
}
export const countValPlus = (data) => {
  return ({
    type: 'COUNT+',
    payload: data
  })
}
export const countValMinus = (data) => {
  return ({
    type: 'COUNT-',
    payload: data
  })
}
export const cartItems = (data) => {
  return ({
    type: 'CART_ITEMS',
    payload: data
  })
}
export const clearCart = (data) => {
  return ({
    type: 'CLEAR_CART',
    payload: data
  })
}
export const materials = (data) => {
  return ({
    type: 'MATERIALS',
    payload: data
  })
}
export const cartItemPlus = (data) => {
  return ({
    type: 'CART_ITEM_PLUS',
    payload: data
  })
}
export const cartItemMinus = (data) => {
  return ({
    type: 'CART_ITEM_MINUS',
    payload: data
  })
}
