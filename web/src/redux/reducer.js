const initialState = { robots: [], counter: 0, cartItem: [], material: [], sameRobot: [] }
export const Reducer = (state = initialState, action) => {
    switch (action.type) {
        case 'SHOW_ROBOTS':
            return ({
                ...state,
                robots: action.payload
            })
        case 'SEARCH_MATERIALS':
            return ({
                ...state,
                robots: action.payload
            })
        case 'COUNT+':
            return ({
                ...state,
                counter: state.counter + 1
            })
        case 'COUNT-':
            return ({
                ...state,
                counter: state.counter - 1
            })
        case 'CART_ITEMS':
            return ({
                ...state,
                cartItem: [...state.cartItem, action.payload]
            })
        case 'CLEAR_CART':
            return ({
                ...state,
                cartItem: [],
                counter: 0
            })
        case 'REMOVE_ITEMS':
            return ({
                ...state,
                cartItem: [action.payload]
            })
        case 'MATERIALS':
            return ({
                ...state,
                material: [...state.material, action.payload]
            })
        case 'CART_ITEM_PLUS':
            return ({
                ...state,
                cartItem: [...state.cartItem, action.payload],
                counter: state.counter + 1
            })
        case 'CART_ITEM_MINUS':
            return ({
                ...state,
                cartItem: action.payload,
                counter: state.counter - 1
            })
        default: return (initialState)
    }
}