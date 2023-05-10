import { createStore } from "redux";
import {Reducer} from './redux/reducer'

const store = createStore(Reducer ,window.__REDUX_DEVTOOLS__ && window.__REDUX_DEVTOOLS_EXTENSION__())

export default store 

