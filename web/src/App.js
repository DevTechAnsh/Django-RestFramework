import React from "react";
import Navbar from "./components/navbar";
import SpacingGrid from "./components/SpacingGrid";
import RecipeReviewCard from './components/cart'
import { Route, Routes, BrowserRouter, Switch } from "react-router-dom";
import Showrobot from './components/showrobot'

const App = () => {
  return (<>
    <BrowserRouter>
      <Navbar />
      <Routes>
        <Route exact path="/" element={<SpacingGrid />} />
        <Route path="/cart" element={<RecipeReviewCard />} />
        <Route path="/showrobot/:id" element={<Showrobot />} />
      </Routes>
    </BrowserRouter>
  </>)
}
export default App
