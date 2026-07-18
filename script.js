const SUPABASE_URL = "https://ykxqciysbwqlzjlcrklj.supabase.co";
const SUPABASE_KEY = "sb_publishable_8pdzj2OOaIOGHVmOuIdQnA_75eP4BgX";

const supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

async function guardarTermino() {
    const titulo = document.getElementById('titulo').value;
    const categoria = document.getElementById('categoria').value; // Nueva línea
    const definicion = document.getElementById('definicion').value;
    const url = document.getElementById('url').value;

    if (!titulo || !definicion || !url || !categoria) {
        alert("¡Llena todos los campos, incluyendo la categoría!");
        return;
    }

    const { error } = await supabaseClient
        .from('terminos')
        .insert([{ 
            titulo: titulo, 
            definicion: definicion, 
            imagen_url: url,
            categoria: categoria // Nueva línea
        }]);

    if (error) alert("Error al guardar: " + error.message);
    else {
        alert("¡Guardado con categoría!");
        // Limpiar formulario
        document.getElementById('titulo').value = '';
        document.getElementById('categoria').value = '';
        document.getElementById('definicion').value = '';
        document.getElementById('url').value = '';
        cargarWiki(); // Refrescar lista
    }
    if (!error) {
        alert("¡Guardado!");
        cerrarModal(); // Cerrar el modal al finalizar
        // ... limpiar campos ...
        cargarWiki();
    }
}

function filtrarTerminos() {
    // Obtenemos el texto del buscador y lo pasamos a minúsculas para comparar mejor
    const filtro = document.getElementById('buscador').value.toLowerCase();
    const tarjetas = document.getElementsByClassName('card');

    // Recorremos todas las tarjetas (excluyendo el formulario)
    // El formulario tiene clase 'form-container', así que no se verá afectado
    for (let i = 0; i < tarjetas.length; i++) {
        const titulo = tarjetas[i].getElementsByTagName('h2')[0].innerText.toLowerCase();
        
        if (titulo.includes(filtro)) {
            tarjetas[i].style.display = ""; // Mostrar
        } else {
            tarjetas[i].style.display = "none"; // Ocultar
        }
    }
}

async function cargarWiki() {
    const { data, error } = await supabaseClient.from('terminos').select('*');
    
    if (error) {
        document.getElementById('contenedor').innerHTML = "Error: " + error.message;
        return;
    }

    document.getElementById('contenedor').innerHTML = data.map((item, index) => {
        const limite = 150; // Cantidad de caracteres a mostrar antes del "Leer más"
        const esLargo = item.definicion.length > limite;
        const textoCortado = esLargo ? item.definicion.substring(0, limite) + "..." : item.definicion;

        return `
            <div class="card" data-categoria="${item.categoria || 'General'}">
                <h2>${item.titulo}</h2>
                <img src="${item.imagen_url}" alt="${item.titulo}">
                <p id="def-${index}">
                    ${textoCortado}
                    ${esLargo ? `<button onclick="toggleDefinicion(${index}, '${btoa(unescape(encodeURIComponent(item.definicion)))}')" style="background:none; border:none; color:#3498db; cursor:pointer; font-weight:bold; padding:0;"> Leer más</button>` : ''}
                </p>
            </div>
        `;
    }).join('');
}

function abrirModal() {
    document.getElementById('modalFormulario').style.display = 'flex';
}

function cerrarModal() {
    document.getElementById('modalFormulario').style.display = 'none';
}

// Función para alternar entre texto corto y largo
function toggleDefinicion(index, definicionBase64) {
    const pElement = document.getElementById(`def-${index}`);
    const definicionCompleta = decodeURIComponent(escape(atob(definicionBase64)));
    
    // Cambiamos el botón a "Leer menos" y mantenemos el mismo estilo
    pElement.innerHTML = definicionCompleta + ` <button onclick="cargarWiki()" style="background:none; border:none; color:#3498db; cursor:pointer; font-weight:bold; padding:0; margin-left: 5px;"> Leer menos</button>`;
}

//Categoria
function filtrarPorCategoria(categoria) {
    const tarjetas = document.getElementsByClassName('card');
    
    for (let i = 0; i < tarjetas.length; i++) {
        // Obtenemos la categoría del atributo data-categoria que crearemos abajo
        const cat = tarjetas[i].getAttribute('data-categoria');
        
        if (categoria === 'Todos' || cat === categoria) {
            tarjetas[i].style.display = "flex"; 
        } else {
            tarjetas[i].style.display = "none";
        }
    }
}

cargarWiki();