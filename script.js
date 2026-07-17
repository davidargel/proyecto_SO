const SUPABASE_URL = "https://ykxqciysbwqlzjlcrklj.supabase.co";
const SUPABASE_KEY = "sb_publishable_8pdzj2OOaIOGHVmOuIdQnA_75eP4BgX";

const supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

async function cargarWiki() {
    const { data, error } = await supabaseClient.from('terminos').select('*');
    
    if (error) {
        document.getElementById('contenedor').innerHTML = "Error: " + error.message;
        return;
    }

    document.getElementById('contenedor').innerHTML = data.map(item => `
        <div class="card">
            <h2>${item.titulo}</h2>
            <img src="${item.imagen_url}" alt="${item.titulo}">
            <p>${item.definicion}</p>
        </div>
    `).join('');
}

async function guardarTermino() {
    const titulo = document.getElementById('titulo').value;
    const definicion = document.getElementById('definicion').value;
    const url = document.getElementById('url').value;

    if (!titulo || !definicion || !url) {
        alert("Llena todos los campos");
        return;
    }

    const { error } = await supabaseClient
        .from('terminos')
        .insert([{ titulo: titulo, definicion: definicion, imagen_url: url }]);

    if (error) alert("Error: " + error.message);
    else {
        alert("¡Guardado!");
        document.getElementById('titulo').value = '';
        document.getElementById('definicion').value = '';
        document.getElementById('url').value = '';
        cargarWiki();
    }
}

cargarWiki();