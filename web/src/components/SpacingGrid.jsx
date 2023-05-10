import * as React from 'react';
import { experimentalStyled as styled } from '@mui/material/styles';
import Box from '@mui/material/Box';
import Paper from '@mui/material/Paper';
import Grid from '@mui/material/Grid';
import data from '../data.json'
import dateFormat from 'dateformat'
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import { Link } from 'react-router-dom'
import { showAllRobots } from '../redux/action';
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Alert from '@mui/material/Alert';
const Item = styled(Paper)(({ theme }) => ({
    backgroundColor: theme.palette.mode === 'dark' ? '#1A2027' : '#fff',
    ...theme.typography.body2,
    padding: theme.spacing(2),
    textAlign: 'center',
    color: theme.palette.text.secondary,
}));
export default function ResponsiveGrid() {
    const dispatch = useDispatch()
    const StoreData = useSelector(state => state.robots)
    const DATA = data.data
    useEffect(() => {
        dispatch(showAllRobots(DATA))
    }, [])
    return (
        <div >
            <Box sx={{ flexGrow: 1 }}>
                <Grid container spacing={{ xs: 2, md: 3 }} columns={{ xs: 4, sm: 8, md: 12 }}>
                    {StoreData.map((value, index) => {
                        return (<>
                            <Grid style={{ background: "#F2F3F5", border: "2px solid black", marginTop: "22px" }} item xs={2} sm={4} md={4} key={index}>
                                <Item style={{ margin: "25px", background: "#ECF3FF", border: "2px solid black" }} ><img src={value.image}></img></Item>
                                <Item style={{ margin: "25px" }}><h8> Name : {value.name}</h8></Item>
                                <Item style={{ margin: "25px" }} ><h8> Price : {value.price}</h8></Item>
                                <Item style={{ margin: "25px" }}>  <h8> Stock : {value.stock}</h8></Item>
                                <Item style={{ margin: "25px" }}><h8> Date :  {dateFormat(value.createdAt, 'dd/mm/yyyy')}</h8></Item>
                                <Item style={{ margin: "25px" }}><h8> Material : {value.material}</h8></Item>
                                <Stack direction="row" alignItems="center" spacing={2}>
                                    <Link to={`/showrobot/${index}`} style={{ textDecoration: 'none' }} >
                                        <Button variant="contained" color="success" style={{ marginLeft: "170px", marginBottom: "10px", textDecoration: "none" }}> view </Button>
                                    </Link>
                                </Stack>
                            </Grid>
                        </>)
                    })}
                    {StoreData.length == 0 ? <Stack sx={{ width: '100%', width: "80%", margin: "auto", marginTop: '50px' }} spacing={2}>
                        <Alert severity="error">No Data Found.......! Search did not match </Alert>
                    </Stack> : ''}
                </Grid>
            </Box>
        </div>
    );
}