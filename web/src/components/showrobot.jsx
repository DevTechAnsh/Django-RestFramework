
import * as React from 'react';
import { styled } from '@mui/material/styles';
import Card from '@mui/material/Card';
import CardHeader from '@mui/material/CardHeader';
import CardMedia from '@mui/material/CardMedia';
import CardContent from '@mui/material/CardContent';
import CardActions from '@mui/material/CardActions';
import Collapse from '@mui/material/Collapse';
import Avatar from '@mui/material/Avatar';
import IconButton from '@mui/material/IconButton';
import Typography from '@mui/material/Typography';
import { red } from '@mui/material/colors';
import FavoriteIcon from '@mui/icons-material/Favorite';
import ShareIcon from '@mui/icons-material/Share';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import data from '../data.json'
import { useParams } from 'react-router-dom';
import dateFormat from 'dateformat';
import { useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Button from '@mui/material/Button';
import { cartItems, materials, countValPlus, countValMinus } from '../redux/action'
import { Navigate } from 'react-router-dom';
const DATA = data.data
const ExpandMore = styled((props) => {
  const { expand, ...other } = props;
  return <IconButton {...other} />;
})(({ theme, expand }) => ({
  transform: !expand ? 'rotate(0deg)' : 'rotate(180deg)',
  marginLeft: 'auto',
  transition: theme.transitions.create('transform', {
    duration: theme.transitions.duration.shortest,
  }),
}));
const Showrobot = () => {
  const dispatch = useDispatch()
  const robo_material = useSelector(state => state.material)
  const [expanded, setExpanded] = React.useState(false);
  const { id } = useParams()
  const [count, setCount] = useState(0)
  const [view, setView] = useState('')
  const [nvigate, setNavigate] = useState()
  const selected_robot = (DATA[id])
  const Plus = () => {
    if (selected_robot.stock != 0 && count != selected_robot.stock) {
      setCount(count + 1)
      if (robo_material.length <= 5) {
        dispatch(cartItems(selected_robot))
        dispatch(countValPlus())
      }
      else {
        alert("cannot add more than 5 items")
      }
    }
    else {
      alert("Product is out of stock ")
    }
  }
  const Minus = () => {
    if (count > 1) {
      setCount(count - 1)
      dispatch(countValMinus())
    }
  }
  const buy_robot = () => {
    dispatch(materials(selected_robot.material))
    setNavigate(true)
  }
  const show = (e) => {
    if (selected_robot.stock == 0) {
      alert("This product is out of stock ")
      setView('')
    }
    else {
      setView(true)
    }
  }
  const handleExpandClick = () => {
    setExpanded(!expanded);
    setView('')
  };
  return (
    <Card sx={{ maxWidth: 345 }} style={{ margin: "auto", marginTop: "50px" }} >
      {nvigate && <Navigate to={`/cart`} />}
      <CardHeader
        avatar={
          <Avatar sx={{ bgcolor: red[500] }} aria-label="recipe">
            {selected_robot.name[0]}
          </Avatar>
        }
        action={
          <IconButton aria-label="settings">
            <MoreVertIcon />
          </IconButton>
        }
        title={selected_robot.name}
        subheader={dateFormat(selected_robot.createdAt, 'dd/mm/yyyy')}
      />
      <CardMedia
        component="img"
        height="194"
        image={selected_robot.image}
        alt="Paella dish"
      />
      <CardContent>
        <Typography variant="body2" color="text.secondary">
          This impressive paella is a perfect party dish and a fun meal to cook
          together with your guests. Add 1 cup of frozen peas along with the mussels,
          if you like.
        </Typography>
      </CardContent>
      <CardActions disableSpacing>
        <IconButton aria-label="add to favorites">
          <FavoriteIcon />
        </IconButton>
        <IconButton aria-label="share">
          <ShareIcon />
        </IconButton>
        <ExpandMore
          expand={expanded}
          onClick={handleExpandClick}
          aria-expanded={expanded}
          aria-label="show more"
        >
          <ExpandMoreIcon />
        </ExpandMore>
      </CardActions>
      <Collapse in={expanded} timeout="auto" unmountOnExit>
        <CardContent>
          <Typography paragraph>Method:</Typography>
          <Typography paragraph>
            Heat 1/2 cup of the broth in a pot until simmering, add saffron and set
            aside for 10 minutes.
          </Typography>
          <Typography paragraph>
            Heat oil in a (14- to 16-inch) paella pan or a large, deep skillet over
            .
          </Typography>
          <Typography paragraph>
            Add rice and stir very gently to distribute. Top with artichokes and

          </Typography>
          <Typography>
            Set aside off of the heat to let rest for 10 minutes, and then serve.
          </Typography>
        </CardContent>
      </Collapse>
      <label htmlFor="icon-button-file" style={{ margin: "auto", marginBottom: "20px" }} >
        {view ? <div>
          <Button variant="contained" onClick={Minus}>-</Button>
          <span style={{ margin: "3px 3px 3px 3px" }}> {count} </span>
          <Button variant="contained" onClick={Plus} >+ </Button>
          {selected_robot.stock == 0 ?
            <div> out of stock...!</div> :
            <Button variant="contained" color="success" style={{ margin: "4px 4px 4px 4px" }} onClick={buy_robot}>Buy</Button>}
        </div> : ''}
        {!view && <Button variant="contained" color="success" style={{ margin: "4px 4px 4px 4px" }} onClick={show} > Add to cart </Button>}
      </label>
    </Card>
  );
}
export default Showrobot