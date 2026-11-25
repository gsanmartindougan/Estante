export const games = [
 {id:1174180,title:'Red Dead Redemption 2',genre:'Aventura',studio:'Rockstar Games',year:2019,hours:'42,8',last:'Ayer',launcher:'Steam',favorite:true,description:'América, 1899. El final de la era del salvaje oeste ha comenzado. Recorre un mundo abierto lleno de vida y escribe tu propia historia junto a la banda de Van der Linde.'},
 {id:1245620,title:'ELDEN RING',genre:'Rol',studio:'FromSoftware',year:2022,hours:'86,2',last:'Hace 3 días',launcher:'Steam',favorite:true,description:'Álzate, Sinluz. Explora las Tierras Intermedias y descubre los misterios del poder del Círculo de Elden.'},
 {id:1086940,title:"Baldur’s Gate 3",genre:'Rol',studio:'Larian Studios',year:2023,hours:'24,5',last:'Hace una semana',launcher:'Steam',favorite:false,description:'Reúne a tu grupo y regresa a los Reinos Olvidados. Una aventura donde cada decisión deja su huella.'},
 {id:1145360,title:'Hades',genre:'Acción',studio:'Supergiant Games',year:2020,hours:'18,3',last:'Hace 2 días',launcher:'Heroic',favorite:true,description:'Desafía al dios de los muertos y escapa del inframundo en una aventura que comienza de nuevo con cada intento.'},
 {id:1091500,title:'Cyberpunk 2077',genre:'Rol',studio:'CD PROJEKT RED',year:2020,hours:'31,0',last:'Hace 5 días',launcher:'Steam',favorite:false,description:'Tu historia comienza en Night City. Conviértete en una leyenda en una ciudad obsesionada con el poder y las modificaciones corporales.'},
 {id:413150,title:'Stardew Valley',genre:'Simulación',studio:'ConcernedApe',year:2016,hours:'63,4',last:'Hace 4 días',launcher:'Steam',favorite:true,description:'Una vieja granja, unas pocas herramientas y una nueva vida por delante. Encuentra tu lugar en el valle.'},
 {id:367520,title:'Hollow Knight',genre:'Aventura',studio:'Team Cherry',year:2017,hours:'12,1',last:'Hace una semana',launcher:'Heroic',favorite:false,description:'Desciende a un reino de insectos y héroes. Descubre los secretos que duermen bajo la superficie de Hallownest.'},
 {id:292030,title:'The Witcher 3: Wild Hunt',genre:'Rol',studio:'CD PROJEKT RED',year:2015,hours:'104,2',last:'Hace 2 semanas',launcher:'Faugus',favorite:false,description:'Ponte en la piel de Geralt de Rivia y busca a la niña de la profecía en un vasto mundo de monstruos y decisiones difíciles.'},
 {id:105600,title:'Terraria',genre:'Aventura',studio:'Re-Logic',year:2011,hours:'9,0',last:'Hace un mes',launcher:'Steam',favorite:false,description:'Excava, lucha, explora y construye. Un mundo de aventuras está esperando bajo tus pies.'},
 {id:620,title:'Portal 2',genre:'Puzles',studio:'Valve',year:2011,hours:'8,5',last:'Hace un mes',launcher:'Steam',favorite:true,description:'Piensa con portales y encuentra la salida de los laboratorios de Aperture Science.'},
 {id:504230,title:'Celeste',genre:'Plataformas',studio:'Maddy Makes Games',year:2018,hours:'6,2',last:'Hace 3 semanas',launcher:'Heroic',favorite:false,description:'Ayuda a Madeline a sobrevivir a sus demonios interiores en su viaje hasta la cima de la montaña Celeste.'},
 {id:990080,title:'Hogwarts Legacy',genre:'Aventura',studio:'Avalanche Software',year:2023,hours:'21,0',last:'Hace un mes',launcher:'Steam',favorite:false,description:'Explora un mundo de magia y descubre una historia que todavía no se ha escrito.'}
];
export const artwork = (game, type='library_600x900_2x.jpg') => game.local ? '' : `https://cdn.akamai.steamstatic.com/steam/apps/${game.id}/${type}`;
export function filterGames(items, query='', category='Todos', letter='') {
 const normalize = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
 return items.filter(g => normalize(g.title).includes(normalize(query)) && (category === 'Todos' || category === 'Favoritos' && g.favorite || g.genre === category) && (!letter || normalize(g.title).startsWith(normalize(letter))));
}

export function libraryLayout(width, height) {
 const columns = width < 600 ? 2 : width < 1000 ? 3 : 4;
 const rows = height < 850 ? 1 : 2;
 return {columns, rows, pageSize: columns * rows, neighbors: width < 500 ? 1 : width < 1000 ? 3 : 5};
}
export function centeredGames(items, selectedId, count, anchor = Math.floor(Math.min(count, items.length) / 2)) {
 if (!items.length) return [];
 const size = Math.min(count, items.length);
 const index = Math.max(0, items.findIndex(game => game.id === selectedId));
 return Array.from({length: size}, (_, offset) => items[(index - anchor + offset + items.length) % items.length]);
}
